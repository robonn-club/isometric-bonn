"""A deterministic triangle rasteriser with a depth buffer, in plain NumPy.

Why not the GPU: this is the reference renderer. It needs no driver and no JIT, and its
output is bit-identical on every machine and in every window: vertices are integers in
1/16 px, coverage is decided by exact integer edge functions with a top-left style rule
(a pixel centre on an edge shared by two triangles belongs to exactly one of them), and
ties in depth go to the lower triangle index. So a 1024 x 1024 render equals its four
512 x 512 tiles byte for byte, which is the plan's seam test. A GPU path (moderngl) can
replace it for all of Bonn behind the same interface.

Work is vectorised by grouping triangles by the power-of-two size of their pixel bounding
box, so every group is one dense NumPy block.
"""

from __future__ import annotations

import numpy as np

from .projection import SUBPIXEL

_HALF = SUBPIXEL // 2


def _next_pow2(a: np.ndarray) -> np.ndarray:
    a = np.maximum(a, 1)
    return (1 << np.ceil(np.log2(a)).astype(np.int64)).astype(np.int64)


def rasterize(x: np.ndarray, y: np.ndarray, d: np.ndarray, width: int, height: int,
              chunk: int = 1 << 22) -> tuple[np.ndarray, np.ndarray]:
    """Rasterise triangles into a width x height window.

    x, y: (n, 3) int64 vertex positions in 1/16 px relative to the window origin.
    d:    (n, 3) float64 depth per vertex (smaller is nearer).
    Returns (tri, depth): (height, width) int64 triangle index (-1 where empty) and
    float64 depth (inf where empty).
    """
    x = np.asarray(x, dtype=np.int64)
    y = np.asarray(y, dtype=np.int64)
    d = np.asarray(d, dtype=np.float64)
    tri_buf = np.full(width * height, -1, dtype=np.int64)
    z_buf = np.full(width * height, np.inf)
    if len(x) == 0:
        return tri_buf.reshape(height, width), z_buf.reshape(height, width)

    area = (x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0])
    # Make every triangle positively oriented, so "inside" means all edge functions >= 0.
    flip = area < 0
    if flip.any():
        x, y, d = x.copy(), y.copy(), d.copy()
        x[flip, 1], x[flip, 2] = x[flip, 2].copy(), x[flip, 1].copy()
        y[flip, 1], y[flip, 2] = y[flip, 2].copy(), y[flip, 1].copy()
        d[flip, 1], d[flip, 2] = d[flip, 2].copy(), d[flip, 1].copy()
        area = np.abs(area)

    # Pixel px is covered when its centre (16 px + 8) is inside.
    xmin = -((-(x.min(1) - _HALF)) // SUBPIXEL)
    xmax = (x.max(1) - _HALF) // SUBPIXEL
    ymin = -((-(y.min(1) - _HALF)) // SUBPIXEL)
    ymax = (y.max(1) - _HALF) // SUBPIXEL
    xmin = np.maximum(xmin, 0)
    ymin = np.maximum(ymin, 0)
    xmax = np.minimum(xmax, width - 1)
    ymax = np.minimum(ymax, height - 1)
    live = (area > 0) & (xmin <= xmax) & (ymin <= ymax)
    ids = np.nonzero(live)[0]
    if len(ids) == 0:
        return tri_buf.reshape(height, width), z_buf.reshape(height, width)

    # Edge (a -> b) owns the pixel centres lying exactly on it when it points down, or
    # left when horizontal. Reversed, the rule flips, so a shared edge has one owner.
    edges = ((1, 2), (2, 0), (0, 1))  # opposite vertex 0, 1, 2
    own = []
    for a, b in edges:
        dx = x[:, b] - x[:, a]
        dy = y[:, b] - y[:, a]
        own.append((dy > 0) | ((dy == 0) & (dx < 0)))

    sx = _next_pow2(xmax[ids] - xmin[ids] + 1)
    sy = _next_pow2(ymax[ids] - ymin[ids] + 1)
    key = sx * 65536 + sy
    order = np.argsort(key, kind="stable")
    ids, sx, sy, key = ids[order], sx[order], sy[order], key[order]
    starts = np.r_[0, np.nonzero(np.diff(key))[0] + 1, len(key)]

    for g0, g1 in zip(starts[:-1], starts[1:]):
        bx, by = int(sx[g0]), int(sy[g0])
        per = max(1, chunk // (bx * by))
        ax = np.arange(bx, dtype=np.int64)[None, None, :]
        ay = np.arange(by, dtype=np.int64)[None, :, None]
        for c0 in range(g0, g1, per):
            t = ids[c0:min(c0 + per, g1)]
            gx = xmin[t][:, None, None] + ax
            gy = ymin[t][:, None, None] + ay
            mask = (gx <= xmax[t][:, None, None]) & (gy <= ymax[t][:, None, None])
            cx = gx * SUBPIXEL + _HALF
            cy = gy * SUBPIXEL + _HALF
            w = []
            for k, (a, b) in enumerate(edges):
                xa, ya = x[t, a][:, None, None], y[t, a][:, None, None]
                ex = (x[t, b] - x[t, a])[:, None, None]
                ey = (y[t, b] - y[t, a])[:, None, None]
                wk = ex * (cy - ya) - ey * (cx - xa)
                mask &= (wk > 0) | ((wk == 0) & own[k][t][:, None, None])
                w.append(wk)
            ti, yy, xx = np.nonzero(mask)
            if len(ti) == 0:
                continue
            tt = t[ti]
            gxs = xmin[tt] + xx
            gys = ymin[tt] + yy
            w0 = w[0][ti, yy, xx].astype(np.float64)
            w1 = w[1][ti, yy, xx].astype(np.float64)
            w2 = w[2][ti, yy, xx].astype(np.float64)
            dep = (w0 * d[tt, 0] + w1 * d[tt, 1] + w2 * d[tt, 2]) / area[tt]
            pix = gys * width + gxs
            _merge(tri_buf, z_buf, pix, dep, tt)

    return tri_buf.reshape(height, width), z_buf.reshape(height, width)


def _merge(tri_buf, z_buf, pix, dep, tri):
    """Keep, per pixel, the fragment with the smallest (depth, triangle index)."""
    o = np.lexsort((tri, dep, pix))
    p = pix[o]
    first = np.ones(len(p), dtype=bool)
    first[1:] = p[1:] != p[:-1]
    o = o[first]
    p, dd, tt = pix[o], dep[o], tri[o]
    cur_d, cur_t = z_buf[p], tri_buf[p]
    better = (dd < cur_d) | ((dd == cur_d) & (tt < cur_t))
    z_buf[p[better]] = dd[better]
    tri_buf[p[better]] = tt[better]
