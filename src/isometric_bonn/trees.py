"""Trees: one rounded crown per tree instead of a canopy carpet.

nDOM50 gives the canopy as one surface. Here it is split into single crowns: crown tops are
local maxima of the smoothed height, and a watershed from those tops divides the canopy into
one region per tree. Each region is then rebuilt as a dome (broadleaf) or a cone (conifer)
from its own top height and size, so every tree gets its own shading, outline and colour.
Trees with a clear stem below the crown get a trunk.

Everything is computed on the global 0.5 m grid of world positions, so a crown is the same
in every tile.
"""

from __future__ import annotations

import zlib

import numpy as np
from scipy import ndimage


def conifer_hint(lu, px, forest_classes, conifer_cls, mixed_cls):
    """1 where a tree is likely a conifer: the cadastre's conifer forest, or, in mixed forest
    and elsewhere, dark crowns that reflect little infrared (needles in May)."""
    luma = 0.299 * px[..., 0] + 0.587 * px[..., 1] + 0.114 * px[..., 2]
    nir = px[..., 3]
    dark_mixed = (luma < 75) & (nir < 120)
    dark_strict = (luma < 42) & (nir < 70)  # outside forests most trees are broadleaf
    forest = np.isin(lu, forest_classes)
    hint = (lu == conifer_cls) | ((lu == mixed_cls) & dark_mixed) | (~forest & dark_strict)
    return hint.astype(np.float32)


def crowns(tree_h, veg, hint, e0, n0, res, cfg):
    """See _crowns; averages over crown labels emptied as fragments are NaN and zeroed there."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return _crowns(tree_h, veg, hint, e0, n0, res, cfg)


def _crowns(tree_h, veg, hint, e0, n0, res, cfg):
    """Segment the canopy into crowns and rebuild their surface.

    Returns the rebuilt height above ground per cell (0 outside crowns), the crown label per
    cell (0 outside), and per crown: conifer flag, colour variant, top, base, and peak
    position (row, col) and radius in cells.
    """
    hs = ndimage.gaussian_filter(tree_h, cfg["crown_peak_smooth"])
    size = int(cfg["crown_spacing_cells"])
    peaks = (hs >= ndimage.maximum_filter(hs, size=size)) & (tree_h > cfg["tree_min_height"]) & veg
    lab, n = segment(hs, veg, peaks)
    empty = (np.zeros_like(tree_h), np.zeros(tree_h.shape, np.int32),
             {k: np.zeros(0) for k in ("conifer", "variant", "top", "base", "row", "col", "radius")})
    if n == 0:
        return empty
    # Drop fragments too small to read as a tree.
    cells = np.bincount(lab.ravel(), minlength=n + 1).astype(np.float64)
    small = cells < cfg["crown_min_cells"]
    small[0] = False
    lab[small[lab]] = 0
    idx = np.arange(1, n + 1)
    top = np.asarray(ndimage.maximum(tree_h, lab, idx), dtype=np.float64)
    top = np.nan_to_num(top)
    rc = np.array(ndimage.center_of_mass(np.ones_like(lab), lab, idx), dtype=np.float64).reshape(-1, 2)
    rc = np.nan_to_num(rc)
    row, col = rc[:, 0], rc[:, 1]
    conifer = np.nan_to_num(np.asarray(ndimage.mean(hint, lab, idx), dtype=np.float64)) > 0.5
    base = top * np.where(conifer, cfg["conifer_base"], cfg["crown_base"])
    # A stable colour variant per tree, from its world position.
    e = np.round((e0 + (col + 0.5) * res) * 2).astype(np.int64)
    nn = np.round((n0 - (row + 0.5) * res) * 2).astype(np.int64)
    variant = np.array([zlib.crc32(f"{a},{b}".encode()) % 3 for a, b in zip(e, nn)], dtype=np.int64)

    # Shape each crown from its own outline: height rises with the distance from the crown's
    # edge (where it meets another crown or open ground), so a crown fills its region as a
    # rounded pillow (broadleaf) or a cone (conifer), and neighbours stay apart.
    edge = np.zeros(lab.shape, dtype=bool)
    for ax in (0, 1):
        for d in (1, -1):
            edge |= lab != np.roll(lab, d, axis=ax)
    inner = (lab > 0) & ~edge
    dist = ndimage.distance_transform_edt(inner) + (lab > 0)
    dmax = np.nan_to_num(np.asarray(ndimage.maximum(dist, lab, idx), dtype=np.float64))
    radius = np.maximum(dmax, 1.0)  # cells from edge to centre
    r_, c_ = np.nonzero(lab)
    k = lab[r_, c_] - 1
    x = np.clip(dist[r_, c_] / radius[k], 0, 1)
    pillow = base[k] + (top[k] - base[k]) * np.sqrt(1 - (1 - x) ** 2)  # a round, full crown
    cone = base[k] + (top[k] - base[k]) * x
    h = np.zeros_like(tree_h)
    h[r_, c_] = np.where(conifer[k], cone, pillow)
    info = {"conifer": conifer, "variant": variant, "top": top, "base": base,
            "row": row, "col": col, "radius": radius}
    return h, lab, info


def _uphill(hs, mask):
    """Index of each cell's highest neighbour (8 around), or of itself at a local top."""
    rows, cols = hs.shape
    idx = np.arange(rows * cols).reshape(rows, cols)
    val = np.where(mask, hs, -np.inf)
    best_v, best_i = val.copy(), idx.copy()
    pv = np.pad(val, 1, constant_values=-np.inf)
    pi = np.pad(idx, 1, constant_values=-1)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            nv = pv[1 + dy:1 + dy + rows, 1 + dx:1 + dx + cols]
            ni = pi[1 + dy:1 + dy + rows, 1 + dx:1 + dx + cols]
            better = mask & (nv > best_v)
            best_v = np.where(better, nv, best_v)
            best_i = np.where(better, ni, best_i)
    return best_i.ravel()


def _follow(ptr):
    """Follow pointers to their end (pointer doubling)."""
    for _ in range(64):
        nxt = ptr[ptr]
        if np.array_equal(nxt, ptr):
            break
        ptr = nxt
    return ptr


def segment(hs, veg, peaks):
    """Crown regions: steepest ascent to a local top, then every region without a real crown
    top (from `peaks`) joins the neighbouring region it shares its highest saddle with.
    Boundaries fall at saddles, as in a watershed. Returns labels (0 outside) and their count."""
    rows, cols = hs.shape
    root = _follow(_uphill(hs, veg))
    flat_v = veg.ravel()
    roots, basin = np.unique(root[flat_v], return_inverse=True)
    nb = len(roots)
    if nb == 0:
        return np.zeros(hs.shape, np.int32), 0
    lab = np.full(rows * cols, -1, dtype=np.int64)
    lab[flat_v] = basin
    major = np.zeros(nb, dtype=bool)
    major[lab[np.flatnonzero(peaks.ravel() & flat_v)]] = True
    top = hs.ravel()[roots]

    # Highest saddle to any other basin, over 4-neighbour pairs.
    hsf, labg = hs.ravel(), lab.reshape(rows, cols)
    a = np.concatenate([labg[:, :-1].ravel(), labg[:-1, :].ravel()])
    b = np.concatenate([labg[:, 1:].ravel(), labg[1:, :].ravel()])
    ia = np.concatenate([np.arange(rows * cols).reshape(rows, cols)[:, :-1].ravel(),
                         np.arange(rows * cols).reshape(rows, cols)[:-1, :].ravel()])
    ib = ia + np.concatenate([np.ones((rows, cols - 1), np.int64).ravel(),
                              np.full((rows - 1, cols), cols, np.int64).ravel()])
    pair = (a >= 0) & (b >= 0) & (a != b)
    a, b = a[pair], b[pair]
    sad = np.minimum(hsf[ia[pair]], hsf[ib[pair]])
    src = np.concatenate([a, b])
    dst = np.concatenate([b, a])
    sad = np.concatenate([sad, sad])
    order = np.lexsort((-sad, src))
    first = np.ones(len(order), dtype=bool)
    first[1:] = src[order][1:] != src[order][:-1]
    target = np.arange(nb)
    best = order[first]
    minor = ~major[src[best]]
    target[src[best][minor]] = dst[best][minor]
    # Two minor basins pointing at each other: the higher one becomes the root.
    loop = (target[target] == np.arange(nb)) & (target != np.arange(nb))
    keep_self = loop & (top >= top[target])
    target[keep_self] = np.flatnonzero(keep_self)
    target = _follow(target)
    final = np.unique(target, return_inverse=True)[1].astype(np.int32) + 1
    out = np.zeros(rows * cols, dtype=np.int32)
    out[flat_v] = final[basin]
    return out.reshape(rows, cols), int(final.max())


def canopy_surface(h, lab, info):
    """Vertex heights of the floating canopy mesh, the cells to draw, and a per-cell subtype
    (conifer * 4 + variant). Just outside a crown the surface stays at the crown's base, so
    the crown keeps a clean edge and open space below it."""
    is_tree = lab > 0
    near = ndimage.maximum_filter(lab, size=3)  # nearest crown label for rim cells
    base_of = np.concatenate([[0.0], info["base"]]) if len(info["base"]) else np.zeros(1)
    rim = ~is_tree & (near > 0)
    vh = np.where(is_tree, h, np.where(rim, base_of[near], 0.0))
    t = is_tree.astype(np.int8)
    cells = (t[:-1, :-1] + t[:-1, 1:] + t[1:, 1:] + t[1:, :-1]) >= 1
    sub_of = np.concatenate([[0], (info["conifer"].astype(np.int64) * 4 + info["variant"])]) \
        if len(info["base"]) else np.zeros(1, np.int64)
    cell_lab = np.maximum(np.maximum(near[:-1, :-1], near[:-1, 1:]), np.maximum(near[1:, 1:], near[1:, :-1]))
    cell_sub = sub_of[cell_lab].astype(np.uint8)
    return vh, cells, cell_sub


def trunks(info, ee, nn, ground, cfg):
    """A square trunk under every crown that is tall enough to show one: (n, 3, 3) triangles."""
    keep = (info["top"] >= cfg["trunk_min_height"]) & (info["radius"] >= cfg["trunk_min_radius_cells"])
    if not keep.any():
        return np.zeros((0, 3, 3))
    r = np.clip(np.round(info["row"][keep]).astype(int), 0, ee.shape[0] - 1)
    c = np.clip(np.round(info["col"][keep]).astype(int), 0, ee.shape[1] - 1)
    e, n, z0 = ee[r, c], nn[r, c], ground[r, c] - 0.5
    z1 = ground[r, c] + info["base"][keep] - 0.2
    s = cfg["trunk_width"] / 2
    corners = [(-s, -s), (s, -s), (s, s), (-s, s)]
    tris = []
    for i in range(4):
        (ax, ay), (bx, by) = corners[i], corners[(i + 1) % 4]
        p0 = np.stack([e + ax, n + ay, z0], -1)
        p1 = np.stack([e + bx, n + by, z0], -1)
        p2 = np.stack([e + bx, n + by, z1], -1)
        p3 = np.stack([e + ax, n + ay, z1], -1)
        tris.append(np.stack([p0, p1, p2], 1))
        tris.append(np.stack([p0, p2, p3], 1))
    return np.concatenate(tris)
