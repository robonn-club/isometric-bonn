"""Gridded inputs: bare-ground height (DGM1), height above ground (nDOM50), aerial photo (DOP10).

All three come as 1 km tiles in EPSG:25832, named by their south-west corner in km. A
`Grid` mosaics the tiles a job needs and samples them at world positions.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from .fetch import local_file

# DOP tiles are 10,000 px squares from a trusted public server; allow that size explicitly.
Image.MAX_IMAGE_PIXELS = 10_000 * 10_000 + 1

DOP_REDUCE = 2  # 10 cm -> 40 cm: enough for 2 px/m, and four times faster to decode


@dataclass
class Grid:
    data: np.ndarray  # (rows, cols) or (rows, cols, bands); row 0 is the north edge
    e0: float  # west edge, metres
    n0: float  # north edge, metres
    res: float  # metres per cell

    def index(self, e, n):
        col = np.floor((np.asarray(e) - self.e0) / self.res).astype(np.int64)
        row = np.floor((self.n0 - np.asarray(n)) / self.res).astype(np.int64)
        return (np.clip(row, 0, self.data.shape[0] - 1), np.clip(col, 0, self.data.shape[1] - 1))

    def nearest(self, e, n):
        r, c = self.index(e, n)
        return self.data[r, c]

    def bilinear(self, e, n):
        """Bilinear interpolation between cell centres (2-D grids only)."""
        x = (np.asarray(e, dtype=np.float64) - self.e0) / self.res - 0.5
        y = (self.n0 - np.asarray(n, dtype=np.float64)) / self.res - 0.5
        x0 = np.clip(np.floor(x).astype(np.int64), 0, self.data.shape[1] - 2)
        y0 = np.clip(np.floor(y).astype(np.int64), 0, self.data.shape[0] - 2)
        fx = np.clip(x - x0, 0, 1)
        fy = np.clip(y - y0, 0, 1)
        d = self.data
        top = d[y0, x0] * (1 - fx) + d[y0, x0 + 1] * fx
        bot = d[y0 + 1, x0] * (1 - fx) + d[y0 + 1, x0 + 1] * fx
        return top * (1 - fy) + bot * fy


def _read(key: str, path: Path) -> np.ndarray:
    if key == "dop10":
        # Decoding a JPEG 2000 tile takes seconds and every tile serves several windows, so
        # the decoded 40 cm image is cached next to the data (25 MB per tile).
        cache = path.parents[2] / "cache" / "dop10" / f"{path.stem}_r{DOP_REDUCE}.npy"
        if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
            return np.load(cache, mmap_mode="r")
        im = Image.open(path)
        im.reduce = DOP_REDUCE
        im.load()
        a = np.asarray(im)  # RGBA, where A carries the infrared band
        if a.ndim != 3 or a.shape[2] != 4:
            raise ValueError(f"{path.name}: expected 4 bands (RGB + infrared), got {a.shape}")
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_name(f"{cache.stem}.{os.getpid()}.tmp.npy")  # parallel workers never clash
        np.save(tmp, a)
        tmp.replace(cache)
        return a
    return np.asarray(Image.open(path), dtype=np.float32)


def mosaic(key: str, data_dir: Path, e_min: float, n_min: float, e_max: float, n_max: float) -> Grid:
    """Mosaic the 1 km tiles of one product that cover a box, cropped to that box."""
    tiles_e = range(math.floor(e_min / 1000), math.floor((e_max - 1e-6) / 1000) + 1)
    tiles_n = range(math.floor(n_min / 1000), math.floor((n_max - 1e-6) / 1000) + 1)
    parts = {}
    res = None
    for te in tiles_e:
        for tn in tiles_n:
            a = _read(key, local_file(data_dir, key, te, tn))
            r = 1000.0 / a.shape[1]
            if res is None:
                res = r
            elif abs(r - res) > 1e-9:
                raise ValueError(f"{key}: tiles differ in resolution")
            parts[(te, tn)] = a
    size = int(round(1000 / res))
    sample = next(iter(parts.values()))
    full = np.zeros((size * len(tiles_n), size * len(tiles_e)) + sample.shape[2:], dtype=sample.dtype)
    for (te, tn), a in parts.items():
        r0 = (tiles_n[-1] - tn) * size
        c0 = (te - tiles_e[0]) * size
        full[r0:r0 + size, c0:c0 + size] = a
    e0 = tiles_e[0] * 1000.0
    n0 = (tiles_n[-1] + 1) * 1000.0
    c_lo = max(0, int(math.floor((e_min - e0) / res)))
    c_hi = min(full.shape[1], int(math.ceil((e_max - e0) / res)))
    r_lo = max(0, int(math.floor((n0 - n_max) / res)))
    r_hi = min(full.shape[0], int(math.ceil((n0 - n_min) / res)))
    return Grid(full[r_lo:r_hi, c_lo:c_hi].copy(), e0 + c_lo * res, n0 - r_lo * res, res)
