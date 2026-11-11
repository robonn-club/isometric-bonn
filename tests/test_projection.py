import numpy as np

from isometric_bonn.geo import lonlat_to_utm32
from isometric_bonn.projection import TILE, Camera, tile_index, tile_origin


def test_ground_lines_are_exact_2_to_1():
    cam = Camera(2.0)
    x0, y0 = cam.screen(365000, 5620000, 60)
    xe, ye = cam.screen(365001, 5620000, 60)
    xn, yn = cam.screen(365000, 5620001, 60)
    assert (xe - x0, ye - y0) == (2.0, -1.0)
    assert (xn - x0, yn - y0) == (-2.0, -1.0)


def test_screen_and_depth_invert_exactly():
    cam = Camera(2.0)
    rng = np.random.default_rng(3)
    e = 365000 + rng.uniform(0, 1000, 500)
    n = 5620000 + rng.uniform(0, 1000, 500)
    z = rng.uniform(40, 200, 500)
    sx, sy = cam.screen(e, n, z)
    e2, n2, z2 = cam.world(sx, sy, cam.depth(e, n, z))
    assert np.abs(e2 - e).max() < 1e-6 and np.abs(n2 - n).max() < 1e-6 and np.abs(z2 - z).max() < 1e-6


def test_bonn_tiles_have_small_positive_indices():
    cam = Camera(2.0)
    x0, y0 = tile_origin(cam)
    assert x0 % TILE == 0 and y0 % TILE == 0
    for e, n in ((360000, 5605000), (375000, 5625000), (365284, 5620793)):
        x, y = cam.screen(e, n, 100)
        tx, ty = tile_index(cam, int(x) // TILE * TILE, int(y) // TILE * TILE)
        assert 0 <= tx < 200 and 0 <= ty < 100


def test_utm_conversion_matches_a_known_point():
    # Cologne Cathedral, EPSG:25832 as published by the city (about 356,560 / 5,645,290).
    e, n = lonlat_to_utm32(6.95828, 50.94133)
    assert abs(e - 356560) < 15 and abs(n - 5645290) < 15
