"""Estimate the sun of the aerial photo from its building shadows.

The plan wants the map's sun to match the photo's light: the photo's brightness colours
the ground, and its shadows are baked in. So we look for the sun position whose LoD2
building shadows best cover the photo's dark paved ground (intersection over union), on a
coarse grid of positions and then a finer one. Trees and grass are left out of the score.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from . import citygml
from .projection import sun_vector
from .rasters import mosaic
from .scene import ShadowMap, bounds_points, footprint_mask, load_buildings, tiles_needed


def estimate(area: dict, style: dict, data_dir: Path, log=print, texel_m: float = 1.0):
    tiles = tiles_needed(area, style)
    ce, cn = area["center"]
    half = 450.0
    e0, n0, e1, n1 = ce - half, cn - half, ce + half, cn + half
    dgm = mosaic("dgm1", data_dir, e0 - 2, n0 - 2, e1 + 2, n1 + 2)
    dop = mosaic("dop10", data_dir, e0, n0, e1, n1)
    ndom = mosaic("ndom50", data_dir, e0, n0, e1, n1)
    b = load_buildings(data_dir, tiles)
    cen = b["tri"].mean(1)
    near = (cen[:, 0] > e0 - 60) & (cen[:, 0] < e1 + 60) & (cen[:, 1] > n0 - 60) & (cen[:, 1] < n1 + 60)
    tri, kind, bld = b["tri"][near], b["tri_kind"][near], b["tri_bld"][near]
    walls_roofs = kind != citygml.KIND_GROUND

    # Evaluation cells: 1 m grid of open, paved ground (no footprint, no plants, nothing tall).
    res = 1.0
    cols = int((e1 - e0) / res)
    rows = int((n1 - n0) / res)
    ee, nn = np.meshgrid(e0 + (np.arange(cols) + 0.5) * res, n1 - (np.arange(rows) + 0.5) * res)
    foot = footprint_mask(tri[kind == citygml.KIND_GROUND], e0, n1, res, ee.shape)
    px = dop.nearest(ee, nn).astype(np.float32)
    ndvi = (px[..., 3] - px[..., 0]) / (px[..., 3] + px[..., 0] + 1e-6)
    luma = 0.299 * px[..., 0] + 0.587 * px[..., 1] + 0.114 * px[..., 2]
    tall = ndom.nearest(ee, nn) > 1.0
    ok = ~foot & (ndvi < 0.15) & ~tall
    dark = luma < np.percentile(luma[ok], 25)
    pts = np.stack([ee[ok], nn[ok], dgm.bilinear(ee[ok], nn[ok])], 1)
    bounds = bounds_points(e0, n0, e1, n1, float(dgm.data.min()) - 5, float(dgm.data.max()) + 80)

    def score(az, el):
        sun = sun_vector(az, el)
        sm = ShadowMap(tri[walls_roofs], bld[walls_roofs], sun, bounds, texel_m)
        sh = sm.query(pts, -1, 0.3, 0.3)
        inter = np.count_nonzero(sh & dark[ok])
        union = np.count_nonzero(sh | dark[ok])
        return inter / max(union, 1)

    results = {}
    for az in range(120, 241, 15):
        for el in (35, 45, 55, 65):
            results[(az, el)] = score(az, el)
    best = max(results, key=results.get)
    log(f"coarse best: azimuth {best[0]}, elevation {best[1]} (IoU {results[best]:.3f})")
    for az in np.arange(best[0] - 10, best[0] + 10.1, 2.5):
        for el in np.arange(best[1] - 7.5, best[1] + 7.6, 2.5):
            key = (float(az), float(el))
            if key not in results:
                results[key] = score(*key)
    best = max(results, key=results.get)
    log(f"fine best: azimuth {best[0]}, elevation {best[1]} (IoU {results[best]:.3f})")
    return best, results
