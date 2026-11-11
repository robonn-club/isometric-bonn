"""Coordinates: ETRS89 / UTM zone 32N (EPSG:25832), the grid of every NRW product we use.

Only one conversion is needed, from latitude/longitude (for places and pins) to that grid.
It uses Krüger's series to third order, accurate to well under a millimetre inside the
zone, so no projection library is required. WGS84 and ETRS89 differ by under a metre in
Bonn, which is far below one map pixel.
"""

from __future__ import annotations

import math

# GRS80 ellipsoid and UTM zone 32 constants.
_A = 6378137.0
_F = 1 / 298.257222101
_K0 = 0.9996
_E0 = 500000.0
_LON0 = math.radians(9.0)

_N = _F / (2 - _F)
_AA = _A / (1 + _N) * (1 + _N**2 / 4 + _N**4 / 64)
_ALPHA = (
    _N / 2 - 2 * _N**2 / 3 + 5 * _N**3 / 16,
    13 * _N**2 / 48 - 3 * _N**3 / 5,
    61 * _N**3 / 240,
)
_C = 2 * math.sqrt(_N) / (1 + _N)


def lonlat_to_utm32(lon: float, lat: float) -> tuple[float, float]:
    """Return (easting, northing) in metres, EPSG:25832, for a WGS84/ETRS89 point."""
    phi = math.radians(lat)
    dlon = math.radians(lon) - _LON0
    t = math.sinh(math.atanh(math.sin(phi)) - _C * math.atanh(_C * math.sin(phi)))
    xi = math.atan2(t, math.cos(dlon))
    eta = math.atanh(math.sin(dlon) / math.sqrt(1 + t * t))
    e = eta + sum(a * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, a in enumerate(_ALPHA, 1))
    n = xi + sum(a * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, a in enumerate(_ALPHA, 1))
    return _E0 + _K0 * _AA * e, _K0 * _AA * n
