"""Cars: parked and moving cars from nDOM50, drawn as small 3D cars.

The height model sees every car as a blob 1-2.6 m above the ground. Blobs of car size on
roads, car parks and yards become a car facing along the blob's long axis, in the colour the
aerial photo shows (white, silver, black, red or blue). Vans and buses are larger and are left
out. Everything uses world positions only, so a car is the same in every tile.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

WHITE, SILVER, BLACK, RED, BLUE = 0, 1, 2, 3, 4
GLASS = 15  # subtype of the cabin's side panels


def detect(hag, veg, foot, deck_h, lu, allowed, px, ee, nn, res, cfg):
    """Return a structured list of cars: centre (e, n), heading, length, width, colour."""
    m = (hag > cfg["car_min_height"]) & (hag < cfg["car_max_height"]) & ~veg & ~foot & (deck_h <= 0) \
        & np.isin(lu, allowed)
    m = ndimage.binary_opening(m, structure=np.ones((2, 2), bool))
    lab, n = ndimage.label(m)
    if n == 0:
        return np.zeros(0, dtype=_DTYPE)
    r, c = np.nonzero(lab)
    k = lab[r, c]
    cnt = np.bincount(k, minlength=n + 1).astype(np.float64)
    s = lambda w: np.bincount(k, weights=w, minlength=n + 1)  # noqa: E731
    mr, mc = s(r) / np.maximum(cnt, 1), s(c) / np.maximum(cnt, 1)
    vrr = s(r * r) / np.maximum(cnt, 1) - mr ** 2
    vcc = s(c * c) / np.maximum(cnt, 1) - mc ** 2
    vrc = s(r * c) / np.maximum(cnt, 1) - mr * mc
    # Principal axes of each blob.
    tr, det = vrr + vcc, vrr * vcc - vrc ** 2
    disc = np.sqrt(np.maximum(tr * tr / 4 - det, 0))
    l1, l2 = tr / 2 + disc, np.maximum(tr / 2 - disc, 0)
    # n cells in a row have centre variance (n^2 - 1) / 12, so the extent is res * sqrt(12 var + 1).
    length = np.sqrt(12 * np.maximum(l1, 0) + 1) * res
    width = np.sqrt(12 * l2 + 1) * res
    # Heading of the long axis in (east, north): rows grow southwards.
    ang_rc = 0.5 * np.arctan2(2 * vrc, vcc - vrr)  # angle from +col towards +row
    heading = np.arctan2(-np.sin(ang_rc), np.cos(ang_rc))
    area = cnt * res * res
    ok = (area >= cfg["car_min_area"]) & (area <= cfg["car_max_area"]) & \
         (length >= 3.0) & (length <= 6.0) & (width >= 1.4) & (width <= 2.4)
    ok[0] = False
    ids = np.nonzero(ok)[0]
    if len(ids) == 0:
        return np.zeros(0, dtype=_DTYPE)
    rgb = np.stack([s(px[r, c, i].astype(np.float64)) / np.maximum(cnt, 1) for i in range(3)], 1)
    out = np.zeros(len(ids), dtype=_DTYPE)
    ri = np.clip(np.round(mr[ids]).astype(int), 0, ee.shape[0] - 1)
    ci = np.clip(np.round(mc[ids]).astype(int), 0, ee.shape[1] - 1)
    out["e"] = ee[ri, ci] + (mc[ids] - ci) * res
    out["n"] = nn[ri, ci] - (mr[ids] - ri) * res
    out["heading"] = heading[ids]
    out["length"] = np.clip(length[ids], 3.8, 5.0)
    out["width"] = np.clip(width[ids], 1.7, 2.0)
    out["colour"] = colour_of(rgb[ids])
    return out


_DTYPE = np.dtype([("e", "f8"), ("n", "f8"), ("heading", "f8"), ("length", "f8"), ("width", "f8"),
                   ("colour", "u1")])


def colour_of(rgb):
    r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    out = np.full(len(rgb), SILVER, dtype=np.uint8)
    out[luma > 165] = WHITE
    out[luma < 65] = BLACK
    out[(r > g + 25) & (r > b + 25) & (luma >= 65)] = RED
    out[(b > r + 18) & (luma >= 65) & (luma <= 165)] = BLUE
    return out


def _box(cx, cy, z0, z1, half_l, half_w, cos, sin):
    """Top and four sides of an oriented box, (n, 10, 3, 3), and which faces are sides."""
    corners = []
    for dl, dw in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        x = cx + dl * half_l * cos - dw * half_w * sin
        y = cy + dl * half_l * sin + dw * half_w * cos
        corners.append((x, y))
    lo = [np.stack([x, y, z0], -1) for x, y in corners]
    hi = [np.stack([x, y, z1], -1) for x, y in corners]
    tris = [np.stack([hi[0], hi[1], hi[2]], 1), np.stack([hi[0], hi[2], hi[3]], 1)]
    for i in range(4):
        j = (i + 1) % 4
        tris += [np.stack([lo[i], lo[j], hi[j]], 1), np.stack([lo[i], hi[j], hi[i]], 1)]
    return np.stack(tris, 1)


def geometry(cars, ground_z):
    """Triangles of all cars, with a subtype per triangle (colour, or GLASS for cabin sides)."""
    if len(cars) == 0:
        return np.zeros((0, 3, 3)), np.zeros(0, np.uint8)
    cos, sin = np.cos(cars["heading"]), np.sin(cars["heading"])
    hl, hw = cars["length"] / 2, cars["width"] / 2
    body = _box(cars["e"], cars["n"], ground_z + 0.3, ground_z + 1.0, hl, hw, cos, sin)
    back = -0.08 * cars["length"]
    cabin = _box(cars["e"] + back * cos, cars["n"] + back * sin, ground_z + 1.0, ground_z + 1.45,
                 hl * 0.55, hw * 0.88, cos, sin)
    n = len(cars)
    col = cars["colour"].astype(np.uint8)
    body_sub = np.repeat(col[:, None], 10, 1)
    cabin_sub = np.concatenate([np.repeat(col[:, None], 2, 1), np.full((n, 8), GLASS, np.uint8)], 1)
    tri = np.concatenate([body, cabin], 1).reshape(-1, 3, 3)
    sub = np.concatenate([body_sub, cabin_sub], 1).reshape(-1)
    return tri, sub
