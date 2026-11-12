"""Churches: drawn so the eye finds them.

LoD2 often ends a church at its nave roof. The Münster's model stops 29 m above ground, while
its crossing tower is 81 m tall; the Kreuzkirche loses its 70 m tower the same way. The height
model (nDOM50) still has the towers. So where it rises well above a church's own LoD2 roof,
and the tip tops everything LoD2 has for that building, a tower is added: a shaft up to the
measured top of its walls and a pyramid spire up to the measured tip.

Each church complex then carries one gold cross on its highest point (style.py draws it). A
complex is the church buildings within `cross_complex_gap_m` of each other: a church and its
freestanding bell tower, or the wings of a monastery, which ALKIS keeps as separate buildings
(one monastery in Bonn's data would otherwise get nine crosses). Twin towers of equal
height keep one each. Walls, windows and roofs get their own colours (style.py, wall_kind and
the roof families).

All of it is decided once per render by `table`, from the LoD2 tiles of the whole render and
fixed-grid rasters around each church, so every window draws the same towers and crosses.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import shapely
from scipy import ndimage

from . import citygml
from .fetch import local_file
from .projection import SUBPIXEL
from .rasterize import rasterize
from .rasters import mosaic

# ALKIS building functions (31001_<n>) drawn as churches. 3040 "building for religious
# purposes" is mostly church towers, sacristies and cloisters in Bonn's data; synagogues,
# mosques and temples have codes of their own and keep the normal look.
CHURCH = {3040, 3041, 3043, 3048}  # religious building, church, chapel, monastery
CROSS_ALWAYS = {3041, 3043}        # church and chapel; 3040 and 3048 only when tall
TOWER_TRIS = 14   # triangles per restored tower (_tower_mesh): 8 wall, 2 top, 4 spire
TWIN_M = 1.5      # a tower this close to its complex's highest point gets a cross too


def function_number(code: str) -> int:
    group, _, num = str(code).partition("_")
    return int(num) if group == "31001" and num.isdigit() else 0


def is_church(code: str) -> bool:
    return function_number(code) in CHURCH


def table(data_dir: Path, tiles, cfg: dict) -> dict[str, np.ndarray]:
    """Towers and crosses for every church in the LoD2 `tiles` (1 km tile indices), decided
    once for a whole render.

    Flat arrays: the tower triangles with their kinds, normals, polygon ids (below -1, so they
    meet neither LoD2's ids nor the -1 of ground and trees) and owner (an index into
    `tower_gid`); and per cross, the building it stands on, its world position and how steep
    the roof is there (metres sideways per metre down, so the renderer can tell how much of a
    needle-thin spire tip falls between pixels).
    """
    blds = _church_buildings(data_dir, tiles)
    towers = []
    for b in blds:
        try:
            towers.append(_towers_of(b["ground"], b["roofs"], data_dir, cfg))
        except FileNotFoundError:
            # A church at the outer edge of the tiles can reach into rasters that no window
            # needed, so none were fetched; no window shows it either.
            towers.append(None)
    picks = place_crosses(blds, towers, cfg)
    gids, owner, tri, kind, normal, poly = [], [], [], [], [], []
    next_id = -2
    for b, tw in zip(blds, towers):
        if tw is None:
            continue
        t, k, f, nrm = tw
        owner.append(np.full(len(t), len(gids), np.int32))
        gids.append(b["gid"])
        tri.append(t)
        kind.append(k)
        normal.append(nrm)
        poly.append(next_id - f)
        next_id -= int(f.max()) + 1

    def cat(parts, shape, dtype):
        return np.concatenate(parts).astype(dtype) if parts else np.zeros(shape, dtype)

    return {"tower_gid": np.asarray(gids, dtype=str), "tower_owner": cat(owner, (0,), np.int32),
            "tower_tri": cat(tri, (0, 3, 3), np.float64), "tower_kind": cat(kind, (0,), np.uint8),
            "tower_normal": cat(normal, (0, 3), np.float64), "tower_poly": cat(poly, (0,), np.int64),
            "cross_gid": np.asarray([blds[i]["gid"] for i, _, _ in picks], dtype=str),
            "cross_xyz": np.asarray([p for _, p, _ in picks], np.float64).reshape(-1, 3),
            "cross_slope": np.asarray([s for _, _, s in picks], np.float64).reshape(-1)}


def _church_buildings(data_dir: Path, tiles) -> list[dict]:
    """Every church building in the tiles once, sorted by id: its function number and its
    ground, roof and upper (all but ground) triangles."""
    found = {}
    for te, tn in tiles:
        t = citygml.load_tile(data_dir, local_file(data_dir, "lod2", te, tn))
        for i in np.flatnonzero([is_church(f) for f in t["bld_function"]]):
            gid = str(t["bld_gmlid"][i])
            if gid in found:
                continue  # listed in two tiles
            m = t["tri_bld"] == i
            tri, kind = t["tri"][m], t["tri_kind"][m]
            ground, roofs = tri[kind == citygml.KIND_GROUND], tri[kind == citygml.KIND_ROOF]
            if len(ground) and len(roofs):
                found[gid] = {"gid": gid, "fn": function_number(t["bld_function"][i]), "ground": ground,
                              "roofs": roofs, "upper": tri[kind != citygml.KIND_GROUND]}
    return [found[g] for g in sorted(found)]


def place_crosses(blds: list[dict], towers: list, cfg: dict) -> list[tuple[int, np.ndarray, float]]:
    """Where the crosses stand: (building index, world position, steepness) for each.

    A building qualifies when its highest point, towers included, is at least
    `cross_min_height` above its ground (`cross_min_height_other` for religious buildings and
    monasteries that are neither church nor chapel). Of the qualifying buildings in one
    complex only the tallest keeps its cross; a restored tower within TWIN_M of that height
    keeps one too, so twin towers stay twins.
    """
    if not blds:
        return []
    foot = [shapely.union_all(shapely.polygons(b["ground"][:, :, :2])) for b in blds]
    parent = list(range(len(blds)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    near = shapely.STRtree(foot).query(foot, predicate="dwithin", distance=float(cfg["cross_complex_gap_m"]))
    for i, j in zip(*near):
        parent[root(int(i))] = root(int(j))
    groups: dict[int, list[int]] = {}
    tops, spires = [], []
    for i, (b, tw) in enumerate(zip(blds, towers)):
        z0 = float(b["ground"][..., 2].min())
        upper = b["upper"] if tw is None else np.concatenate([b["upper"], tw[0]])
        v = upper.reshape(-1, 3)
        apex = v[int(np.argmax(v[:, 2]))]
        rise = float(apex[2]) - z0
        tops.append((apex, _slope_at(upper, apex), rise))
        spires.append([])
        for k in range(0, 0 if tw is None else len(tw[0]), TOWER_TRIS):
            t = tw[0][k:k + TOWER_TRIS]
            tv = t.reshape(-1, 3)
            tip = tv[int(np.argmax(tv[:, 2]))]
            spires[-1].append((tip, _slope_at(t, tip), float(tip[2]) - z0))
        if rise >= cfg["cross_min_height"] and (b["fn"] in CROSS_ALWAYS or rise >= cfg["cross_min_height_other"]):
            groups.setdefault(root(i), []).append(i)
    picks = []
    for members in groups.values():
        best = max(members, key=lambda i: tops[i][2])  # the first of equals, as ids are sorted
        apex, slope, rise = tops[best]
        picks.append((best, apex, slope))
        placed = [apex]
        for i in members:
            for tip, slope_t, rise_t in spires[i]:
                if rise_t >= rise - TWIN_M and min(np.hypot(*(tip[:2] - p[:2])) for p in placed) > 3.0:
                    picks.append((i, tip, slope_t))
                    placed.append(tip)
    return picks


def apply(b: dict, tab: dict) -> tuple[dict, dict]:
    """The buildings `b` (as scene.load_buildings gives them) with the table's towers added,
    and the crosses that stand on them: building index into `b`, world position, steepness."""
    index = {str(g): i for i, g in enumerate(b["bld_gmlid"])}
    cb = np.array([index.get(str(g), -1) for g in tab["cross_gid"]], np.int64)
    ok = cb >= 0
    crosses = {"bld": cb[ok].astype(np.int32), "xyz": tab["cross_xyz"][ok], "slope": tab["cross_slope"][ok]}
    owner = np.array([index.get(str(g), -1) for g in tab["tower_gid"]], np.int64)
    tb = owner[tab["tower_owner"]] if len(owner) else np.zeros(0, np.int64)
    keep = tb >= 0
    if not keep.any():
        return b, crosses
    out = dict(b)
    for k, add in (("tri", tab["tower_tri"]), ("tri_bld", tb), ("tri_kind", tab["tower_kind"]),
                   ("tri_normal", tab["tower_normal"]), ("tri_poly", tab["tower_poly"])):
        out[k] = np.concatenate([b[k], add[keep].astype(b[k].dtype)])
    return out, crosses


def save(tab: dict, path: Path) -> None:
    """Write a table for the window processes to read."""
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.tmp.npz")
    np.savez(tmp, **tab)
    tmp.replace(path)


def load(path: Path) -> dict[str, np.ndarray]:
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


def _slope_at(tris, apex):
    """Metres sideways per metre down along the steepest-flaring edge that meets the apex:
    small for a needle spire, large (or infinite) for a gable or flat top."""
    at = np.all(np.abs(tris - apex) < 1e-6, axis=2)
    if not at.any():
        return np.inf
    v = tris[at.any(1)].reshape(-1, 3)
    dz = apex[2] - v[:, 2]
    dh = np.hypot(v[:, 0] - apex[0], v[:, 1] - apex[1])
    ok = dz > 0.05
    return float((dh[ok] / dz[ok]).max()) if ok.any() else np.inf


def _towers_of(ground, roofs, data_dir, cfg):
    """Read the height model, terrain and photo around one church and find its towers."""
    pad = 3.0
    e_min, n_min = ground[..., 0].min() - pad, ground[..., 1].min() - pad
    e_max, n_max = ground[..., 0].max() + pad, ground[..., 1].max() + pad
    nd = mosaic("ndom50", data_dir, e_min, n_min, e_max, n_max)
    dg = mosaic("dgm1", data_dir, e_min - 2, n_min - 2, e_max + 2, n_max + 2)
    dop = mosaic("dop10", data_dir, e_min - 1, n_min - 1, e_max + 1, n_max + 1)
    return find_towers(ground, roofs, nd, dg, dop, cfg)


def find_towers(ground, roofs, nd, dg, dop, cfg):
    """Tower triangles for one church, with their kinds, a face number and a normal per
    triangle, or None when its LoD2 already holds everything the height model shows.
    nd, dg and dop are the height model, terrain and photo (rasters.Grid) around it."""
    rows, cols = nd.data.shape
    res = nd.res

    def raster(tris, value):
        x = np.rint((tris[:, :, 0] - nd.e0) / res * SUBPIXEL).astype(np.int64)
        y = np.rint((nd.n0 - tris[:, :, 1]) / res * SUBPIXEL).astype(np.int64)
        return rasterize(x, y, value, cols, rows)

    foot = raster(ground, np.zeros(ground.shape[:2]))[0] >= 0
    t_roof, d_roof = raster(roofs, -roofs[:, :, 2])  # the topmost roof wins
    roof_z = np.where(t_roof >= 0, -d_roof, np.nan)
    rr, cc = np.mgrid[0:rows, 0:cols]
    ce, cn = nd.e0 + (cc + 0.5) * res, nd.n0 - (rr + 0.5) * res
    dsm = dg.bilinear(ce, cn) + nd.data
    px = dop.nearest(ce, cn).astype(np.float64)
    ndvi = (px[..., 3] - px[..., 0]) / (px[..., 3] + px[..., 0] + 1e-6)
    with np.errstate(invalid="ignore"):
        excess = np.where(foot & np.isfinite(roof_z), dsm - roof_z, -np.inf)
    # A missing tower rises well above the roof under it, and above everything LoD2 has for
    # the building: lower roof parts that LoD2 merely got wrong stay below that line.
    top_lod2 = float(roofs[..., 2].max())
    core = (excess > cfg["tower_min_excess"]) & (dsm > top_lod2 + cfg["tower_min_rise"])
    lab, n = ndimage.label(core, structure=np.ones((3, 3), bool))
    if n == 0:
        return None
    z_base = float(ground[..., 2].min())
    tris, kinds, faces, normals = [], [], [], []
    face0 = 0
    for k in range(1, n + 1):
        m = lab == k
        cells = int(m.sum())
        if cells < cfg["tower_min_cells"] or float(ndvi[m].mean()) > cfg["tower_max_ndvi"]:
            continue
        peak = float(dsm[m].max())
        if peak - z_base < cfg["tower_min_height"]:
            continue  # church towers are taller; this is LoD2 and the height model disagreeing
        rect = shapely.minimum_rotated_rectangle(shapely.MultiPoint(np.stack([ce[m], cn[m]], 1)))
        if rect.geom_type != "Polygon":
            continue
        xy = np.asarray(rect.exterior.coords)[:4]
        centre = xy.mean(0)
        ax_u, ax_v = xy[1] - xy[0], xy[2] - xy[1]
        len_u, len_v = np.linalg.norm(ax_u) + res, np.linalg.norm(ax_v) + res  # cell centres -> edges
        if len_u < 1e-6 or len_v < 1e-6:
            continue
        ax_u, ax_v = ax_u / np.linalg.norm(ax_u), ax_v / np.linalg.norm(ax_v)
        short, long_ = min(len_u, len_v), max(len_u, len_v)
        if long_ / short > cfg["tower_max_aspect"] or cells * res * res / (len_u * len_v) < cfg["tower_min_fill"]:
            continue
        # The top of the walls: the height along the tower's outer ring. The spire: the part
        # clearly above it, narrower than the tower when the height model says so.
        ring = m & ~ndimage.binary_erosion(m, structure=np.ones((3, 3), bool))
        eave = min(float(np.median(dsm[ring])), peak - 1.0)
        rise = max(peak - eave, 1.5)
        above = float((m & (dsm > eave + 2.0)).sum()) * res * res
        side = np.sqrt(above) / max(1.0 - 2.0 / rise, 0.35) if above > 0 else 0.45 * short
        side = float(np.clip(side, 0.45 * short, short))
        t, kd, fc = _tower_mesh(centre, ax_u, ax_v, len_u / 2, len_v / 2, z_base, eave, eave + rise, side / 2)
        tris.append(t)
        kinds.append(kd)
        faces.append(fc + face0)
        normals.append(_normals(t, centre))
        face0 += int(fc.max()) + 1
    if not tris:
        return None
    return np.concatenate(tris), np.concatenate(kinds), np.concatenate(faces), np.concatenate(normals)


def _tower_mesh(c, u, v, hu, hv, z0, z1, z2, hs):
    """A box from z0 to z1 over the rectangle (centre c, unit axes u and v, half sizes hu, hv),
    a flat top, and a square pyramid of half size hs from z1 to the apex at z2."""
    corners = [c - hu * u - hv * v, c + hu * u - hv * v, c + hu * u + hv * v, c - hu * u + hv * v]
    tris, kinds, faces = [], [], []
    for f in range(4):
        a, bb = corners[f], corners[(f + 1) % 4]
        p0, p1 = np.r_[a, z0], np.r_[bb, z0]
        p2, p3 = np.r_[bb, z1], np.r_[a, z1]
        tris += [[p0, p1, p2], [p0, p2, p3]]
        kinds += [citygml.KIND_WALL] * 2
        faces += [f, f]
    top = [np.r_[p, z1] for p in corners]
    tris += [[top[0], top[1], top[2]], [top[0], top[2], top[3]]]
    kinds += [citygml.KIND_ROOF] * 2
    faces += [4, 4]
    base = [c - hs * u - hs * v, c + hs * u - hs * v, c + hs * u + hs * v, c - hs * u + hs * v]
    apex = np.r_[c, z2]
    for f in range(4):
        tris.append([np.r_[base[f], z1 + 0.05], np.r_[base[(f + 1) % 4], z1 + 0.05], apex])
        kinds.append(citygml.KIND_ROOF)
        faces.append(5 + f)
    return np.asarray(tris, np.float64), np.asarray(kinds, np.uint8), np.asarray(faces, np.int64)


def _normals(tris, centre):
    """Outward unit normals of one tower's faces: walls point away from its axis, roofs up."""
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    out = tris.mean(1)[:, :2] - np.asarray(centre)[None, :2]
    flip = np.where(np.abs(n[:, 2]) > 0.2, n[:, 2] < 0, (n[:, :2] * out).sum(1) < 0)
    n[flip] *= -1
    return n
