"""Render the data layers of one window of the map.

A window is a rectangle of the global pixel grid, snapped to 512 px tiles. Rendering it
records, per pixel: material, building, surface normal, depth, world position, the aerial
photo's colour and infrared there, sun shadow, and position on a wall. Styling then works
on these layers alone (style.py), so the look can change without the raw data.

Geometry:
- LoD2 roofs and walls. Wall bottoms are pushed 3 m into the ground so buildings on slopes
  never float above the terrain mesh.
- One height mesh at 0.5 m: bare ground (DGM1) plus trees, where trees are nDOM50 heights
  kept only where the photo's infrared says plants and no LoD2 footprint lies. Cars, signs
  and roof edges in nDOM50 are therefore dropped.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
import shapely
from scipy import ndimage

from . import citygml
from .fetch import local_file
from .projection import SUBPIXEL, Camera, sun_vector, tile_window
from .rasterize import rasterize
from .rasters import mosaic

# Materials in the `mat` layer.
EMPTY, GROUND, TREE, ROOF, WALL, WATER, DECK = 0, 1, 2, 3, 4, 5, 6
MATERIALS = {"empty": EMPTY, "ground": GROUND, "tree": TREE, "roof": ROOF, "wall": WALL, "water": WATER,
             "deck": DECK}

_ZK = math.sqrt(6) / 2


def ground_bounds(cam: Camera, ox: int, oy: int, w: int, h: int, zlo: float, zhi: float, margin: float):
    """Box of ground (E, N) whose points between heights zlo and zhi can appear in the window."""
    p = cam.px_per_m
    es, ns = [], []
    for sx in (ox, ox + w):
        for sy in (oy, oy + h):
            for z in (zlo, zhi):
                v = sx / p
                u = -(2 / p) * (sy + _ZK * p * z)
                es.append((u + v) / 2)
                ns.append((u - v) / 2)
    return min(es) - margin, min(ns) - margin, max(es) + margin, max(ns) + margin


def window_for(area: dict, style: dict, data_dir: Path | None = None):
    """Camera and window origin for an area; the centre height comes from DGM1 if present."""
    cam = Camera(float(style["camera"]["px_per_m"]))
    w, h = area["size_px"]
    ce, cn = area["center"]
    zc = float(area.get("center_height", 60.0))
    if data_dir is not None:
        g = mosaic("dgm1", data_dir, ce - 2, cn - 2, ce + 2, cn + 2)
        zc = float(g.bilinear(ce, cn))
    ox, oy = tile_window(cam, ce, cn, zc, w, h)
    if "origin_px" in area:  # an explicit window, e.g. one tile for the seam test
        ox, oy = (int(v) for v in area["origin_px"])
    return cam, ox, oy, w, h


def tiles_needed(area: dict, style: dict) -> list[tuple[int, int]]:
    """The 1 km data tiles a window needs, from a generous height range for Bonn."""
    cam, ox, oy, w, h = window_for(area, style)
    # A superset of what build_layers can ask for: it first reads heights 40-220 m with this
    # margin plus 2 m, then the real terrain range plus 80 m (at most about 275 m in Bonn).
    margin = float(style["render"].get("shadow_margin_m", 40)) + 22
    e0, n0, e1, n1 = ground_bounds(cam, ox, oy, w, h, 30.0, 300.0, margin)
    return [(e, n) for e in range(math.floor(e0 / 1000), math.floor(e1 / 1000) + 1)
            for n in range(math.floor(n0 / 1000), math.floor(n1 / 1000) + 1)]


# --- buildings ---------------------------------------------------------------------------

def load_buildings(data_dir: Path, tiles) -> dict[str, np.ndarray]:
    """Normalised LoD2 for several tiles, merged; a building listed in two tiles counts once."""
    parts, seen = [], set()
    offset = 0
    for te, tn in tiles:
        t = citygml.load_tile(data_dir, local_file(data_dir, "lod2", te, tn))
        keep_b = np.array([g not in seen for g in t["bld_gmlid"]], dtype=bool)
        seen.update(t["bld_gmlid"][keep_b].tolist())
        new_index = np.cumsum(keep_b) - 1 + offset
        keep_t = keep_b[t["tri_bld"]]
        parts.append({
            "tri": t["tri"][keep_t],
            "tri_bld": new_index[t["tri_bld"][keep_t]].astype(np.int32),
            "tri_kind": t["tri_kind"][keep_t],
            "tri_normal": t["poly_normal"][t["tri_poly"][keep_t]],
            "tri_poly": t["tri_poly"][keep_t].astype(np.int64) + (offset << 24),
            "bld_gmlid": t["bld_gmlid"][keep_b],
            "bld_function": t["bld_function"][keep_b],
            "bld_rooftype": t["bld_rooftype"][keep_b],
            "bld_height": t["bld_height"][keep_b],
        })
        offset += int(keep_b.sum())
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def _sink_wall_bottoms(tri, kind, poly, depth=3.0):
    """Lower the bottom vertices of each wall polygon, staying in the wall's plane."""
    walls = np.nonzero(kind == citygml.KIND_WALL)[0]
    if len(walls) == 0:
        return tri
    tri = tri.copy()
    pid = poly[walls]
    zmin_tri = tri[walls, :, 2].min(1)
    order = np.argsort(pid, kind="stable")
    uniq, start = np.unique(pid[order], return_index=True)
    zmin_poly = np.minimum.reduceat(zmin_tri[order], start)
    zmin = zmin_poly[np.searchsorted(uniq, pid)]
    bottom = tri[walls, :, 2] <= zmin[:, None] + 0.01
    z = tri[walls, :, 2]
    z[bottom] -= depth
    tri[walls, :, 2] = z
    return tri


# --- height mesh ---------------------------------------------------------------------------

def footprint_mask(tri_ground: np.ndarray, e0: float, n0: float, res: float, shape) -> np.ndarray:
    """Rasterise building ground triangles onto a north-up grid (True inside a footprint)."""
    if len(tri_ground) == 0:
        return np.zeros(shape, dtype=bool)
    x = np.rint((tri_ground[:, :, 0] - e0) / res * SUBPIXEL).astype(np.int64)
    y = np.rint((n0 - tri_ground[:, :, 1]) / res * SUBPIXEL).astype(np.int64)
    t, _ = rasterize(x, y, np.zeros(x.shape), shape[1], shape[0])
    return t >= 0


def height_mesh(ndom, dgm, dop, foot, cfg):
    """Vertex heights, tree height above ground, and the vegetation mask on the nDOM grid."""
    rows, cols = ndom.data.shape
    e = ndom.e0 + (np.arange(cols) + 0.5) * ndom.res
    n = ndom.n0 - (np.arange(rows) + 0.5) * ndom.res
    ee, nn = np.meshgrid(e, n)
    ground = dgm.bilinear(ee, nn)
    px = dop.nearest(ee, nn).astype(np.float32)
    ndvi = (px[..., 3] - px[..., 0]) / (px[..., 3] + px[..., 0] + 1e-6)
    hag = ndom.data
    veg = (ndvi > cfg["tree_ndvi"]) & (hag > cfg["tree_min_height"]) & ~foot
    veg = ndimage.binary_opening(veg, iterations=1)
    veg = ndimage.binary_closing(veg, iterations=1) & ~foot
    tree_h = np.where(veg, np.maximum(hag, 0), 0.0)
    tree_h = np.where(veg, ndimage.median_filter(tree_h, size=3), 0.0)
    # Open water is near black in infrared, darker than any shadow. A stand-in for the
    # plan's Basis-DLM water polygons, on the same global grid so tiles still match.
    # Bridges and other raised structures LoD2 lacks: tall, not plants, not a building, and
    # wider than a bus, so vehicles, signs and noise barriers drop out.
    k = int(cfg["deck_min_width_cells"])
    deck = (hag > cfg["deck_min_height"]) & (ndvi < cfg["tree_ndvi"]) & ~foot
    deck = ndimage.binary_opening(deck, structure=np.ones((k, k), bool))
    deck = ndimage.binary_closing(deck, iterations=2) & ~foot
    deck_h = np.where(deck, ndimage.median_filter(np.where(deck, hag, 0.0), size=5), 0.0)
    water = (px[..., 3] < cfg["water_max_infrared"]) & (ndvi < cfg["water_max_ndvi"]) & ~foot & ~veg & ~deck
    water = ndimage.binary_opening(water, iterations=2)
    water = ndimage.binary_closing(water, iterations=2) & ~foot
    return ee, nn, ground, tree_h.astype(np.float64), veg, water, deck_h.astype(np.float64)


def mesh_triangles(z, cells):
    """Two triangles for each selected grid cell.

    Cell (r, c) spans the vertices (r, c), (r, c+1), (r+1, c+1), (r+1, c). It is split
    along the diagonal that best follows the surface.
    """
    cols = z.shape[1]
    r, c = np.nonzero(cells)
    a = r * cols + c
    b, cc, d = a + 1, a + cols + 1, a + cols
    zf = z.ravel()
    use_ac = (np.abs(zf[a] - zf[cc]) <= np.abs(zf[b] - zf[d]))[:, None]
    t1 = np.where(use_ac, np.stack([a, b, cc], 1), np.stack([a, b, d], 1))
    t2 = np.where(use_ac, np.stack([a, cc, d], 1), np.stack([b, cc, d], 1))
    return np.concatenate([t1, t2])


def canopy(tree_h, cfg):
    """Tree crowns as a surface of their own, floating above the ground mesh.

    nDOM50 only knows the top of a crown. Meshed straight down to the ground, crowns turn
    into curtains ("melted trees"). Instead the crown's edge drops only to a share of the
    local tree height, which leaves open space and a shadow under each tree. Returns the
    canopy height above ground per vertex, the cells to draw, and smoothed heights that
    give crowns rounded shading.
    """
    is_tree = tree_h > 0.5
    rim = ndimage.binary_dilation(is_tree, structure=np.ones((3, 3), bool)) & ~is_tree
    peak = ndimage.maximum_filter(tree_h, size=5)
    h = np.where(is_tree, tree_h, np.where(rim, cfg["crown_base"] * peak, 0.0))
    t = is_tree.astype(np.int8)
    cells = (t[:-1, :-1] + t[:-1, 1:] + t[1:, 1:] + t[1:, :-1]) >= 1
    smooth = ndimage.gaussian_filter(h, cfg["crown_smooth"])
    return h, cells, smooth


def deck_surface(deck_h, cfg):
    """Raised decks as slabs of fixed thickness, floating like the tree crowns, so a bridge
    keeps the river visible under it instead of becoming a dam."""
    is_d = deck_h > 0.5
    rim = ndimage.binary_dilation(is_d, structure=np.ones((3, 3), bool)) & ~is_d
    near = ndimage.maximum_filter(deck_h, size=3)
    h = np.where(is_d, deck_h, np.where(rim, np.maximum(near - cfg["deck_thickness"], 0.3), 0.0))
    t = is_d.astype(np.int8)
    cells = (t[:-1, :-1] + t[:-1, 1:] + t[1:, 1:] + t[1:, :-1]) >= 1
    return h, cells


def _normals(tri):
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    n[n[:, 2] < 0] *= -1
    return n


def cells_in_window(vx, vy, ox, oy, w, h, pad=2):
    """Cells whose projected bounding box touches the window."""
    corners_x = (vx[:-1, :-1], vx[:-1, 1:], vx[1:, 1:], vx[1:, :-1])
    corners_y = (vy[:-1, :-1], vy[:-1, 1:], vy[1:, 1:], vy[1:, :-1])
    x0 = np.minimum.reduce(corners_x)
    x1 = np.maximum.reduce(corners_x)
    y0 = np.minimum.reduce(corners_y)
    y1 = np.maximum.reduce(corners_y)
    return (x1 >= ox - pad) & (x0 <= ox + w + pad) & (y1 >= oy - pad) & (y0 <= oy + h + pad)


# --- the render ------------------------------------------------------------------------------

def build_layers(area: dict, style: dict, data_dir: Path, out_dir: Path, log=print, clip=None) -> Path:
    """Render one window's data layers to out_dir/<area name>/layers.npz.

    With `clip` (a shapely polygon, e.g. the city boundary), only ground, trees and buildings
    inside it are drawn; everything still casts shadows. Decisions use world positions only,
    so neighbouring windows agree.
    """
    t_start = time.time()
    cam, ox, oy, w, h = window_for(area, style, data_dir)
    cfg = style["render"]
    tiles = tiles_needed(area, style)
    log(f"window {w}x{h} px at ({ox}, {oy}); data tiles {tiles}")

    # Ground box with the real height range.
    e0, n0, e1, n1 = ground_bounds(cam, ox, oy, w, h, 40.0, 220.0, 60.0)
    dgm = mosaic("dgm1", data_dir, e0 - 2, n0 - 2, e1 + 2, n1 + 2)
    zlo, zhi = float(dgm.data.min()) - 5, float(dgm.data.max()) + 80
    e0, n0, e1, n1 = ground_bounds(cam, ox, oy, w, h, zlo, zhi, float(cfg.get("shadow_margin_m", 40)))
    ndom = mosaic("ndom50", data_dir, e0, n0, e1, n1)
    dop = mosaic("dop10", data_dir, e0, n0, e1, n1)
    log(f"rasters loaded ({time.time() - t_start:.0f} s)")

    # Buildings near the box.
    b = load_buildings(data_dir, tiles)
    cen = b["tri"].mean(1)
    near = (cen[:, 0] > e0) & (cen[:, 0] < e1) & (cen[:, 1] > n0) & (cen[:, 1] < n1)
    for k in ("tri", "tri_bld", "tri_kind", "tri_normal", "tri_poly"):
        b[k] = b[k][near]
    b["tri"] = _sink_wall_bottoms(b["tri"], b["tri_kind"], b["tri_poly"])
    ground_tris = b["tri"][b["tri_kind"] == citygml.KIND_GROUND]
    foot = footprint_mask(ground_tris, ndom.e0, ndom.n0, ndom.res, ndom.data.shape)
    keep_bld = None
    if clip is not None:
        # A building belongs to the area when its footprint's centre does.
        nbt = len(b["bld_gmlid"])
        gmask = b["tri_kind"] == citygml.KIND_GROUND
        gc = b["tri"][gmask].mean(1)
        cnt = np.bincount(b["tri_bld"][gmask], minlength=nbt)
        ce_ = np.bincount(b["tri_bld"][gmask], weights=gc[:, 0], minlength=nbt) / np.maximum(cnt, 1)
        cn_ = np.bincount(b["tri_bld"][gmask], weights=gc[:, 1], minlength=nbt) / np.maximum(cnt, 1)
        keep_bld = np.zeros(nbt, dtype=bool)
        has = cnt > 0
        keep_bld[has] = shapely.contains_xy(clip, ce_[has], cn_[has])
    log(f"{len(np.unique(b['tri_bld']))} buildings, {len(b['tri'])} triangles "
        f"({time.time() - t_start:.0f} s)")

    # Height meshes: the ground everywhere, and tree crowns floating above it.
    ee, nn, ground, tree_h, veg, water, deck_h = height_mesh(ndom, dgm, dop, foot, cfg)
    ch, c_cells, ch_smooth = canopy(tree_h, cfg)
    zc = ground + ch
    dh, d_cells = deck_surface(deck_h, cfg)
    zd = ground + dh
    e_flat, n_flat = ee.ravel(), nn.ravel()

    def verts(tris, z):
        """(n, 3, 3) vertex positions of grid triangles, built only for the triangles used."""
        return np.stack([e_flat[tris], n_flat[tris], z.ravel()[tris]], -1)

    # Sun shadows. Casters include everything near the window, not only what is visible
    # in it, so a pixel's shadow does not depend on where the window's edge is.
    sun = sun_vector(style["sun"]["azimuth"], style["sun"]["elevation"])
    cast_b = b["tri_kind"] != citygml.KIND_GROUND
    tree_tris = mesh_triangles(zc, c_cells)
    deck_tris = mesh_triangles(zd, d_cells)
    smap = ShadowMap(np.concatenate([b["tri"][cast_b], verts(tree_tris, zc), verts(deck_tris, zd)]),
                     np.concatenate([b["tri_bld"][cast_b], np.full(len(tree_tris), -2), np.full(len(deck_tris), -3)]),
                     sun, bounds_points(e0, n0, e1, n1, zlo, zhi), cfg["shadow_texel_m"])
    del tree_tris, deck_tris
    # Deep shadow on asphalt is as dark in infrared as water, so water must lie in the sun.
    cand = np.flatnonzero(water)
    pts = np.stack([e_flat[cand], n_flat[cand], ground.ravel()[cand]], 1)
    water = water.copy()
    water.ravel()[cand[smap.query(pts, -1, cfg["shadow_bias_m"], cfg["shadow_bias_m"])]] = False
    water = finish_water(water, ndom.res, cfg["water_min_area_m2"])
    del pts, cand
    log(f"shadow map and water ({time.time() - t_start:.0f} s)")
    vx, vy = cam.screen(ee, nn, ground)
    g_cells = cells_in_window(vx, vy, ox, oy, w, h)
    if clip is not None:
        # A grid cell belongs to the area when its centre does.
        r_, c_ = np.nonzero(g_cells)
        ce_ = (ee[r_, c_] + ee[r_, c_ + 1]) / 2
        cn_ = (nn[r_, c_] + nn[r_ + 1, c_]) / 2
        g_cells[r_, c_] = shapely.contains_xy(clip, ce_, cn_)
    g_tris = mesh_triangles(ground, g_cells)
    wv = water.astype(np.int8)
    water_cell = (wv[:-1, :-1] + wv[:-1, 1:] + wv[1:, 1:] + wv[1:, :-1]) >= 3
    g_water = np.tile(water_cell[g_cells], 2)
    vx, vy = cam.screen(ee, nn, zc)
    c_in = c_cells & cells_in_window(vx, vy, ox, oy, w, h)
    if clip is not None:
        r_, c_ = np.nonzero(c_in)
        ce_ = (ee[r_, c_] + ee[r_, c_ + 1]) / 2
        cn_ = (nn[r_, c_] + nn[r_ + 1, c_]) / 2
        c_in[r_, c_] = shapely.contains_xy(clip, ce_, cn_)
    c_tris = mesh_triangles(zc, c_in)
    vx, vy = cam.screen(ee, nn, zd)
    d_in = d_cells & cells_in_window(vx, vy, ox, oy, w, h)
    if clip is not None:
        r_, c_ = np.nonzero(d_in)
        ce_ = (ee[r_, c_] + ee[r_, c_ + 1]) / 2
        cn_ = (nn[r_, c_] + nn[r_ + 1, c_]) / 2
        d_in[r_, c_] = shapely.contains_xy(clip, ce_, cn_)
    d_tris = mesh_triangles(zd, d_in)
    del vx, vy

    # Assemble the main render: buildings (roof, wall), ground mesh, canopy.
    show = b["tri_kind"] != citygml.KIND_GROUND
    if keep_bld is not None:
        show &= keep_bld[b["tri_bld"]]
    btri = b["tri"][show]
    bsx, bsy = cam.screen(btri[..., 0], btri[..., 1], btri[..., 2])
    bin_ = ((bsx.max(1) >= ox - 2) & (bsx.min(1) <= ox + w + 2) &
            (bsy.max(1) >= oy - 2) & (bsy.min(1) <= oy + h + 2))
    btri = btri[bin_]
    bkind = b["tri_kind"][show][bin_]
    bbld = b["tri_bld"][show][bin_]
    bnorm = b["tri_normal"][show][bin_].astype(np.float64)
    bpoly = b["tri_poly"][show][bin_]

    gtri = verts(g_tris, ground)
    ctri = verts(c_tris, zc)
    dtri = verts(d_tris, zd)
    tri = np.concatenate([btri, gtri, ctri, dtri])
    mat = np.concatenate([np.where(bkind == citygml.KIND_ROOF, ROOF, WALL),
                          np.where(g_water, WATER, GROUND), np.full(len(ctri), TREE),
                          np.full(len(dtri), DECK)]).astype(np.uint8)
    n_mesh = len(gtri) + len(ctri) + len(dtri)
    bld = np.concatenate([bbld, np.full(n_mesh, -1)]).astype(np.int32)
    normal = np.concatenate([bnorm, _normals(gtri), _normals(verts(c_tris, ground + ch_smooth)), _normals(dtri)])
    poly = np.concatenate([bpoly, np.full(n_mesh, -1)])
    if len(tri) == 0:  # nothing of the area falls in this window (a corner at a city's edge)
        mat, bld = np.zeros(1, np.uint8), np.full(1, -1, np.int32)
        normal, poly = np.zeros((1, 3)), np.full(1, -1)
    log(f"main pass: {len(tri)} triangles ({len(btri)} building, {len(gtri)} ground, {len(ctri)} canopy)")

    x, y = cam.snap(tri[..., 0], tri[..., 1], tri[..., 2], (ox, oy))
    dep = cam.depth(tri[..., 0], tri[..., 1], tri[..., 2])
    t_r = time.time()
    tri_id, depth = rasterize(x, y, dep, w, h)
    log(f"rasterised in {time.time() - t_r:.0f} s")

    hit = tri_id >= 0
    tid = np.where(hit, tri_id, 0)
    px_mat = np.where(hit, mat[tid], EMPTY).astype(np.uint8)
    px_bld = np.where(hit, bld[tid], -1).astype(np.int32)
    px_n = normal[tid]
    view = cam.view_dir()
    facing_away = (px_n @ view) > 0
    px_n[facing_away] *= -1  # we always see the outside of a closed surface
    gx = ox + np.arange(w) + 0.5
    gy = oy + np.arange(h) + 0.5
    sxg, syg = np.meshgrid(gx, gy)
    we, wn, wz = cam.world(sxg, syg, np.where(hit, depth, 0.0))
    photo = dop.nearest(we, wn)
    photo[~hit] = 0
    agl = wz - dgm.bilinear(we, wn)

    me = np.where(px_mat == TREE, -2, np.where(px_mat == DECK, -3, px_bld))
    shadow = np.zeros(hit.shape, dtype=bool)
    shadow[hit] = smap.query(np.stack([we[hit], wn[hit], wz[hit]], 1), me[hit],
                             cfg["shadow_bias_m"], cfg["shadow_self_bias_m"])
    log(f"shadows done ({time.time() - t_start:.0f} s)")

    # Position on walls, for windows: metres along the wall and above its bottom.
    wall_u, wall_h, wall_len = wall_coords(b, poly, tid, hit & (px_mat == WALL), we, wn, wz)

    roof_rgb, roof_luma, roof_ndvi, roof_cells = roof_stats(b, dop, smap, cfg)

    out = out_dir / area["name"]
    out.mkdir(parents=True, exist_ok=True)
    used = np.unique(px_bld[px_bld >= 0])
    remap = np.full(len(b["bld_gmlid"]), -1, dtype=np.int32)
    remap[used] = np.arange(len(used), dtype=np.int32)
    px_bld = np.where(px_bld >= 0, remap[np.maximum(px_bld, 0)], -1).astype(np.int32)
    e_ref, n_ref = float(area["center"][0]), float(area["center"][1])
    np.savez_compressed(
        out / "layers.npz",
        mat=px_mat, bld=px_bld, normal=px_n.astype(np.float32),
        depth=np.where(hit, depth - cam.depth(e_ref, n_ref, 0.0), np.inf).astype(np.float32),
        world=np.stack([we - e_ref, wn - n_ref, wz], -1).astype(np.float32),
        photo=photo.astype(np.uint8), shadow=shadow, agl=agl.astype(np.float32),
        wall_u=wall_u.astype(np.float32), wall_h=wall_h.astype(np.float32),
        wall_len=wall_len.astype(np.float32),
        bld_function=b["bld_function"][used], bld_height=b["bld_height"][used],
        bld_gmlid=b["bld_gmlid"][used],
        bld_roof_rgb=roof_rgb[used].astype(np.float32), bld_roof_luma=roof_luma[used].astype(np.float32),
        bld_roof_ndvi=roof_ndvi[used].astype(np.float32), bld_roof_cells=roof_cells[used],
        bld_rooftype=b["bld_rooftype"][used],
    )
    meta = {
        "area": area["name"], "title": area.get("title", area["name"]),
        "origin_px": [ox, oy], "size_px": [w, h], "px_per_m": cam.px_per_m, "tile_px": 512,
        "center": area["center"], "sun": style["sun"], "buildings": int(len(used)),
        "triangles": int(len(tri)), "render_seconds": round(time.time() - t_start, 1),
    }
    (out / "layers.json").write_text(json.dumps(meta, indent=2) + "\n")
    log(f"layers saved to {out} ({time.time() - t_start:.0f} s)")
    return out


class ShadowMap:
    """Depth seen from the sun, on a global texel grid, so a point's shadow does not
    depend on which window asks."""

    def __init__(self, casters, owner, sun, bounds_pts, texel_m):
        self.sun, self.res, self.owner = sun, float(texel_m), owner
        ax = np.cross(sun, [0.0, 0.0, 1.0])
        self.ax = ax / np.linalg.norm(ax)
        self.ay = np.cross(self.ax, sun)
        bx, by = self._xy(bounds_pts)
        self.x0 = math.floor(bx.min()) - 2
        self.y1 = math.ceil(by.max()) + 2  # light space is y-down, like the screen
        self.w = math.ceil(bx.max()) - self.x0 + 3
        self.h = self.y1 - math.floor(by.min()) + 3
        cx, cy = self._xy(casters)
        self.tri, self.d = rasterize(np.rint((cx - self.x0) * SUBPIXEL).astype(np.int64),
                                     np.rint((self.y1 - cy) * SUBPIXEL).astype(np.int64),
                                     -(casters @ sun), self.w, self.h)

    def _xy(self, p):
        return (p @ self.ax) / self.res, (p @ self.ay) / self.res

    def query(self, pts, me, bias, self_bias):
        """True where something of another owner (or the same one, past self_bias) lies
        between the point and the sun."""
        rx, ry = self._xy(pts)
        col = np.clip(np.floor(rx - self.x0).astype(np.int64), 0, self.w - 1)
        row = np.clip(np.floor(self.y1 - ry).astype(np.int64), 0, self.h - 1)
        occ = self.tri[row, col]
        occ_owner = np.where(occ >= 0, self.owner[np.maximum(occ, 0)], -9)
        b = np.where(occ_owner == me, self_bias, bias)
        return (occ >= 0) & (self.d[row, col] < -(pts @ self.sun) - b)


def bounds_points(e0, n0, e1, n1, zlo, zhi):
    return np.array([[e, n, z] for e in (e0, e1) for n in (n0, n1) for z in (zlo, zhi)])


def finish_water(water, res, min_area):
    """Keep water bodies of at least `min_area` square metres."""
    lab, n = ndimage.label(water)
    if n == 0:
        return water
    sizes = np.bincount(lab.ravel()) * res * res
    keep = sizes >= min_area
    keep[0] = False
    return keep[lab]


def roof_stats(b, dop, smap, cfg):
    """Photo colour of every building's sunlit roof, measured on the photo's own grid.

    Done in world space, not from rendered pixels, so a building gets the same roof colour
    in every tile, however much of it a tile shows. Returns per-building means of red,
    green, blue (over the brighter half), brightness and infrared vegetation index.
    """
    nb = len(b["bld_gmlid"])
    roofs = b["tri_kind"] == citygml.KIND_ROOF
    rt, rb = b["tri"][roofs], b["tri_bld"][roofs]
    rows, cols = dop.data.shape[:2]
    x = np.rint((rt[:, :, 0] - dop.e0) / dop.res * SUBPIXEL).astype(np.int64)
    y = np.rint((dop.n0 - rt[:, :, 1]) / dop.res * SUBPIXEL).astype(np.int64)
    tri, dep = rasterize(x, y, -rt[:, :, 2], cols, rows)  # the topmost roof wins
    cell = tri >= 0
    r_i, c_i = np.nonzero(cell)
    owner = rb[tri[cell]]
    pts = np.stack([dop.e0 + (c_i + 0.5) * dop.res, dop.n0 - (r_i + 0.5) * dop.res, -dep[cell]], 1)
    lit = ~smap.query(pts, owner, cfg["shadow_bias_m"], cfg["shadow_self_bias_m"])
    px = dop.data[r_i, c_i].astype(np.float64)[lit]
    owner = owner[lit]
    luma = 0.299 * px[:, 0] + 0.587 * px[:, 1] + 0.114 * px[:, 2]
    ndvi = (px[:, 3] - px[:, 0]) / (px[:, 3] + px[:, 0] + 1e-6)

    def mean(groups, v):
        return np.bincount(groups, weights=v, minlength=nb) / np.maximum(np.bincount(groups, minlength=nb), 1)

    m_luma = mean(owner, luma)
    upper = luma >= m_luma[owner]
    rgb = np.stack([mean(owner[upper], px[upper, k]) for k in range(3)], 1)
    count = np.bincount(owner, minlength=nb)
    return rgb, m_luma, mean(owner, ndvi), count


def wall_coords(b, poly, tid, is_wall, we, wn, wz):
    """Metres along each wall polygon (from its left end), above its original bottom, and
    the polygon's length."""
    wall_u = np.full(we.shape, np.nan)
    wall_h = np.full(we.shape, np.nan)
    wall_len = np.full(we.shape, np.nan)
    if not is_wall.any():
        return wall_u, wall_h, wall_len
    walls = b["tri_kind"] == citygml.KIND_WALL
    wp = b["tri_poly"][walls]
    wt = b["tri"][walls]
    wn_ = b["tri_normal"][walls].astype(np.float64)
    uniq, inv = np.unique(wp, return_inverse=True)
    horiz = np.stack([-wn_[:, 1], wn_[:, 0]], 1)
    horiz /= np.linalg.norm(horiz, axis=1, keepdims=True) + 1e-12
    proj = np.einsum("tvk,tk->tv", wt[:, :, :2], horiz)
    u0 = np.full(len(uniq), np.inf)
    np.minimum.at(u0, inv, proj.min(1))
    u1 = np.full(len(uniq), -np.inf)
    np.maximum.at(u1, inv, proj.max(1))
    zb = np.full(len(uniq), np.inf)
    np.minimum.at(zb, inv, wt[:, :, 2].min(1) + 3.0)  # undo the 3 m sink
    dir_ = np.zeros((len(uniq), 2))
    dir_[inv] = horiz
    pid = poly[tid[is_wall]]
    k = np.searchsorted(uniq, pid)
    k = np.clip(k, 0, len(uniq) - 1)
    ok = uniq[k] == pid
    pe, pn, pz = we[is_wall], wn[is_wall], wz[is_wall]
    u = pe * dir_[k, 0] + pn * dir_[k, 1] - u0[k]
    hh = pz - zb[k]
    wall_u[is_wall] = np.where(ok, u, np.nan)
    wall_h[is_wall] = np.where(ok, hh, np.nan)
    wall_len[is_wall] = np.where(ok, (u1 - u0)[k], np.nan)
    return wall_u, wall_h, wall_len
