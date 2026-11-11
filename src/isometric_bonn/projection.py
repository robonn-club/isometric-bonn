"""The camera: one fixed orthographic view and one global pixel grid for all of Bonn.

The camera looks north-east from the south-west at 30 degrees elevation. That makes ground
lines exact 2:1 pixel slopes. At `p` pixels per metre (plan default 2), going one metre
east moves p px right and p/2 px up the screen; one metre north moves p px left and p/2 px
up; one metre of height moves sqrt(6)/2 * p px up (2.45 px at p = 2).

Screen coordinates are global: every pixel of the map has one fixed address, whatever tile
or window it is rendered in, so tiles line up without seams. They are computed in float64
from absolute EPSG:25832 metres (heights in metres above NHN, reference 0, the same
everywhere), then snapped to 1/16 px, so a vertex lands on the same subpixel in any window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

SUBPIXEL = 16  # vertex snapping, 1/16 px
TILE = 512  # map tile size in px

_C = math.cos(math.radians(30)) / math.sqrt(2)  # depth per metre of E+N (0.612)
_ZK = math.sqrt(6) / 2  # screen px of height per px/m (1.2247)


@dataclass(frozen=True)
class Camera:
    px_per_m: float = 2.0

    # --- forward ---------------------------------------------------------------------------
    def screen(self, e, n, z):
        """Global screen position (x right, y down), float64 px."""
        p = self.px_per_m
        e, n, z = (np.asarray(a, dtype=np.float64) for a in (e, n, z))
        return p * (e - n), -0.5 * p * (e + n) - _ZK * p * z

    @staticmethod
    def depth(e, n, z):
        """Distance along the view direction in metres; larger is farther from the camera."""
        e, n, z = (np.asarray(a, dtype=np.float64) for a in (e, n, z))
        return _C * (e + n) - 0.5 * z

    def snap(self, e, n, z, origin_xy: tuple[int, int]):
        """Fixed-point screen coordinates (int64, 1/16 px) relative to a window's integer origin."""
        sx, sy = self.screen(e, n, z)
        ox, oy = origin_xy
        return (np.rint((sx - ox) * SUBPIXEL).astype(np.int64),
                np.rint((sy - oy) * SUBPIXEL).astype(np.int64))

    # --- inverse ---------------------------------------------------------------------------
    def world(self, sx, sy, d):
        """World (E, N, Z) of a global screen point at view depth d (exact inverse)."""
        p = self.px_per_m
        sx, sy, d = (np.asarray(a, dtype=np.float64) for a in (sx, sy, d))
        # Solve  sy = -p/2 u - ZK p z  and  d = C u - z/2  (C = ZK/2) for u = E + N and z.
        v = sx / p  # E - N
        u = _ZK * d - sy / (2 * p)
        z = -0.5 * d - _ZK * sy / (2 * p)
        return (u + v) / 2, (u - v) / 2, z

    # --- sun -------------------------------------------------------------------------------
    @staticmethod
    def view_dir() -> np.ndarray:
        """Unit vector from the camera into the scene (E, N, Z)."""
        return np.array([_C, _C, -0.5])


def sun_vector(azimuth_deg: float, elevation_deg: float) -> np.ndarray:
    """Unit vector pointing towards the sun; azimuth clockwise from north."""
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    return np.array([math.sin(az) * math.cos(el), math.cos(az) * math.cos(el), math.sin(el)])


def tile_window(cam: Camera, center_e: float, center_n: float, center_z: float,
                width: int, height: int) -> tuple[int, int]:
    """Integer origin of a width x height window around a point, snapped to the tile grid."""
    sx, sy = cam.screen(center_e, center_n, center_z)
    ox = int(math.floor((float(sx) - width / 2) / TILE + 0.5)) * TILE
    oy = int(math.floor((float(sy) - height / 2) / TILE + 0.5)) * TILE
    return ox, oy


# Bonn's box (EPSG:25832 metres, heights in metres above NHN): the 14 x 16 km box of the
# plan's data sizes, with every height the city has. Tile indices count from its top-left
# corner, so every tile of Bonn has a small, positive, permanent index.
BONN_BOX = (360_000.0, 5_605_000.0, 375_000.0, 5_625_000.0, 40.0, 200.0)


def tile_origin(cam: Camera) -> tuple[int, int]:
    """Global pixel of tile (0, 0) at this scale: the top-left of Bonn's box, on the tile grid."""
    e0, n0, e1, n1, z0, z1 = BONN_BOX
    xs, ys = [], []
    for e in (e0, e1):
        for n in (n0, n1):
            for z in (z0, z1):
                x, y = cam.screen(e, n, z)
                xs.append(float(x))
                ys.append(float(y))
    return math.floor(min(xs) / TILE) * TILE, math.floor(min(ys) / TILE) * TILE


def tile_index(cam: Camera, x: int, y: int) -> tuple[int, int]:
    """Index of the tile whose top-left global pixel is (x, y)."""
    x0, y0 = tile_origin(cam)
    return (x - x0) // TILE, (y - y0) // TILE
