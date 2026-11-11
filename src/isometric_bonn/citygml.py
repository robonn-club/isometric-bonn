"""Normalise LoD2 CityGML into triangles.

Each building becomes roof and wall triangles, plus its ground polygons (kept only to cut
footprints out of the height mesh). ClosureSurface is dropped, and nothing under
bldg:address is ever read, so no address can reach the repo or the map.

Output per 1 km tile, cached as data/norm/lod2_<e>_<n>.npz:
  tri      (m, 3, 3) float64  vertices, EPSG:25832 metres and metres above NHN
  tri_bld  (m,) int32         index into the building table
  tri_kind (m,) uint8         KIND_ROOF, KIND_WALL or KIND_GROUND
  tri_poly (m,) int32         source polygon, so triangles of one face can be grouped
  poly_normal (p, 3) float32  unit normal of each source polygon (Newell)
  bld_gmlid, bld_function, bld_rooftype (b,) str;  bld_height (b,) float32
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import shapely

NS = {
    "gml": "http://www.opengis.net/gml",
    "bldg": "http://www.opengis.net/citygml/building/1.0",
}
_G = "{%s}" % NS["gml"]
_B = "{%s}" % NS["bldg"]

KIND_ROOF, KIND_WALL, KIND_GROUND = 1, 2, 3
_SURFACES = {_B + "RoofSurface": KIND_ROOF, _B + "WallSurface": KIND_WALL, _B + "GroundSurface": KIND_GROUND}


def _ring(el) -> np.ndarray | None:
    pos = el.find(_G + "posList")
    if pos is not None and pos.text:
        a = np.array(pos.text.split(), dtype=np.float64)
        dim = int(pos.get("srsDimension", "3"))
        a = a.reshape(-1, dim)
    else:
        pts = [p.text.split() for p in el.iter(_G + "pos") if p.text]
        if not pts:
            return None
        a = np.array(pts, dtype=np.float64)
    if len(a) > 1 and np.allclose(a[0], a[-1]):
        a = a[:-1]
    return a if len(a) >= 3 else None


def parse(path: Path):
    """Yield (gml_id, function, roof_type, height, [(kind, exterior, [interiors])]) per building."""
    for _, el in ET.iterparse(path, events=("end",)):
        if el.tag != _B + "Building":
            continue
        gid = el.get(_G + "id", "")
        func = (el.findtext(_B + "function") or "").strip()
        rtype = (el.findtext(_B + "roofType") or "").strip()
        try:
            height = float(el.findtext(_B + "measuredHeight") or "nan")
        except ValueError:
            height = float("nan")
        polys = []
        for surf in el.iter():
            kind = _SURFACES.get(surf.tag)
            if kind is None:
                continue
            for poly in surf.iter(_G + "Polygon"):
                ext = poly.find(_G + "exterior")
                ring = _ring(ext.find(_G + "LinearRing")) if ext is not None else None
                if ring is None:
                    continue
                holes = []
                for itr in poly.findall(_G + "interior"):
                    r = _ring(itr.find(_G + "LinearRing"))
                    if r is not None:
                        holes.append(r)
                polys.append((kind, ring, holes))
        el.clear()
        yield gid, func, rtype, height, polys


def _newell(ring: np.ndarray) -> np.ndarray:
    r = ring - ring.mean(0)
    nxt = np.roll(r, -1, axis=0)
    return np.array([
        np.sum((r[:, 1] - nxt[:, 1]) * (r[:, 2] + nxt[:, 2])),
        np.sum((r[:, 2] - nxt[:, 2]) * (r[:, 0] + nxt[:, 0])),
        np.sum((r[:, 0] - nxt[:, 0]) * (r[:, 1] + nxt[:, 1])),
    ])


def normalise(path: Path) -> dict[str, np.ndarray]:
    """Parse one LoD2 tile and triangulate every roof, wall and ground polygon."""
    gmlids, funcs, rtypes, heights = [], [], [], []
    shapes, poly_bld, poly_kind, poly_normal, poly_origin, poly_drop = [], [], [], [], [], []
    origin = None
    for b, (gid, func, rtype, height, polys) in enumerate(parse(path)):
        gmlids.append(gid)
        funcs.append(func)
        rtypes.append(rtype)
        heights.append(height)
        for kind, ext, holes in polys:
            if origin is None:
                origin = np.floor(ext[0])
            nrm = _newell(ext)
            length = np.linalg.norm(nrm)
            if length < 1e-6:  # area under ~0.5e-6 m2: degenerate
                continue
            nrm = nrm / length
            drop = int(np.argmax(np.abs(nrm)))
            keep = [i for i in range(3) if i != drop]
            c0 = ext.mean(0)
            to2d = lambda r: (r - origin)[:, keep]  # noqa: E731
            shapes.append(shapely.Polygon(to2d(ext), [to2d(h) for h in holes]))
            poly_bld.append(b)
            poly_kind.append(kind)
            poly_normal.append(nrm)
            poly_origin.append(c0)
            poly_drop.append(drop)

    shapes = np.array(shapes, dtype=object)
    poly_normal = np.array(poly_normal, dtype=np.float64).reshape(-1, 3)
    poly_origin = np.array(poly_origin, dtype=np.float64).reshape(-1, 3)
    poly_drop = np.array(poly_drop, dtype=np.int64)
    if len(shapes) == 0:  # a tile without buildings (river, forest, edge of the data)
        return {
            "tri": np.zeros((0, 3, 3)), "tri_bld": np.zeros(0, np.int32), "tri_kind": np.zeros(0, np.uint8),
            "tri_poly": np.zeros(0, np.int32), "poly_normal": np.zeros((0, 3), np.float32),
            "bld_gmlid": np.array(gmlids, dtype=str), "bld_function": np.array(funcs, dtype=str),
            "bld_rooftype": np.array(rtypes, dtype=str), "bld_height": np.array(heights, dtype=np.float32),
        }
    bad = ~shapely.is_valid(shapes)
    if bad.any():
        shapes[bad] = shapely.make_valid(shapes[bad])
    tris = shapely.constrained_delaunay_triangles(shapes)
    parts, src = shapely.get_parts(tris, return_index=True)
    is_poly = shapely.get_type_id(parts) == 3
    parts, src = parts[is_poly], src[is_poly]
    xy = shapely.get_coordinates(parts).reshape(len(parts), 4, 2)[:, :3]

    # Back to 3D: the dropped coordinate comes from the polygon's plane.
    nrm, c0, drop = poly_normal[src], poly_origin[src] - origin, poly_drop[src]
    m = len(parts)
    rows = np.arange(m)
    keep_idx = np.array([[1, 2], [0, 2], [0, 1]])[drop]  # (m, 2)
    n_drop = nrm[rows, drop]
    out = np.zeros((m, 3, 3))
    for v in range(3):
        out[rows, v, keep_idx[:, 0]] = xy[:, v, 0]
        out[rows, v, keep_idx[:, 1]] = xy[:, v, 1]
        # n . (p - c0) = 0  =>  p[drop] = c0[drop] - sum_{k != drop} n_k (p_k - c0_k) / n_drop
        acc = np.zeros(m)
        for k in range(3):
            acc += np.where(drop == k, 0.0, nrm[:, k] * (out[:, v, k] - c0[:, k]))
        out[rows, v, drop] = c0[rows, drop] - acc / n_drop
    out += origin

    return {
        "tri": out,
        "tri_bld": np.array(poly_bld, dtype=np.int32)[src],
        "tri_kind": np.array(poly_kind, dtype=np.uint8)[src],
        "tri_poly": src.astype(np.int32),
        "poly_normal": poly_normal.astype(np.float32),
        "bld_gmlid": np.array(gmlids),
        "bld_function": np.array(funcs),
        "bld_rooftype": np.array(rtypes),
        "bld_height": np.array(heights, dtype=np.float32),
    }


def load_tile(data_dir: Path, gml_path: Path) -> dict[str, np.ndarray]:
    """Normalised triangles for one tile, cached next to the raw data."""
    cache = data_dir / "norm" / (gml_path.stem.lower().replace("_nw", "") + ".npz")
    if cache.exists() and cache.stat().st_mtime >= gml_path.stat().st_mtime:
        with np.load(cache) as z:
            return {k: z[k] for k in z.files}
    res = normalise(gml_path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_name(f"{cache.stem}.{os.getpid()}.tmp.npz")  # parallel workers never clash
    np.savez_compressed(tmp, **res)
    tmp.replace(cache)
    return res
