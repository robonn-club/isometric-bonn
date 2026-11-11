import numpy as np

from isometric_bonn.rasterize import rasterize


def _fan(n_side=7, size=60 * 16, jitter=2 * 16, seed=1):
    """A jittered grid of triangles that tiles a square with shared edges and vertices."""
    rng = np.random.default_rng(seed)
    g = np.linspace(0, size, n_side + 1)
    gx, gy = np.meshgrid(g, g)
    inner = (slice(1, -1), slice(1, -1))
    gx[inner] += rng.integers(-jitter, jitter, gx[inner].shape)
    gy[inner] += rng.integers(-jitter, jitter, gy[inner].shape)
    gx, gy = gx.astype(np.int64) + 37, gy.astype(np.int64) + 21  # off the pixel grid
    tris = []
    for i in range(n_side):
        for j in range(n_side):
            a, b, c, d = (i, j), (i, j + 1), (i + 1, j + 1), (i + 1, j)
            tris += [(a, b, c), (a, c, d)] if (i + j) % 2 else [(a, b, d), (b, c, d)]
    x = np.array([[gx[v] for v in t] for t in tris])
    y = np.array([[gy[v] for v in t] for t in tris])
    area = (x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0])
    assert (area > 0).all() or (area < 0).all(), "test mesh folds over itself"
    return x, y


def test_shared_edges_cover_each_pixel_exactly_once():
    x, y = _fan()
    d = np.zeros(x.shape)
    union, _ = rasterize(x, y, d, 80, 80)
    count = np.zeros((80, 80), int)
    for i in range(len(x)):  # each triangle alone
        t, _ = rasterize(x[i:i + 1], y[i:i + 1], d[i:i + 1], 80, 80)
        count += t >= 0
    assert count.max() == 1, "a pixel is covered twice"
    assert ((union >= 0) == (count == 1)).all(), "a hole between triangles"
    # The square's interior is fully covered.
    assert (union[4:60, 4:60] >= 0).all()


def test_window_position_does_not_change_pixels():
    """One 1024 x 1024 render equals its four 512 x 512 tiles, byte for byte."""
    rng = np.random.default_rng(7)
    n = 3000
    cx = rng.uniform(-50, 1074, n)
    cy = rng.uniform(-50, 1074, n)
    x = np.rint((cx[:, None] + rng.uniform(-40, 40, (n, 3))) * 16).astype(np.int64)
    y = np.rint((cy[:, None] + rng.uniform(-40, 40, (n, 3))) * 16).astype(np.int64)
    d = rng.uniform(0, 100, (n, 3))
    full_t, full_d = rasterize(x, y, d, 1024, 1024, chunk=1 << 16)
    for ty in (0, 1):
        for tx in (0, 1):
            t, dd = rasterize(x - tx * 512 * 16, y - ty * 512 * 16, d, 512, 512)
            sl = (slice(ty * 512, ty * 512 + 512), slice(tx * 512, tx * 512 + 512))
            assert np.array_equal(t, full_t[sl])
            assert np.array_equal(dd, full_d[sl])


def test_nearer_triangle_wins():
    x = np.array([[0, 320, 0], [0, 320, 0]]) + 8
    y = np.array([[0, 0, 320], [0, 0, 320]]) + 8
    d = np.array([[5.0, 5, 5], [2.0, 2, 2]])
    t, dep = rasterize(x, y, d, 20, 20)
    assert t[2, 2] == 1 and dep[2, 2] == 2.0


def test_edges_through_pixel_centres_have_one_owner():
    """Vertices on pixel centres: the diagonal, vertical and horizontal edges all hit centres."""
    c = lambda i: 16 * i + 8  # noqa: E731  pixel centre in 1/16 px
    quads = [(0, 0, 10, 10), (10, 0, 20, 10), (0, 10, 10, 20), (10, 10, 20, 20)]
    xs, ys = [], []
    for x0, y0, x1, y1 in quads:
        xs += [[c(x0), c(x1), c(x1)], [c(x0), c(x1), c(x0)]]
        ys += [[c(y0), c(y0), c(y1)], [c(y0), c(y1), c(y1)]]
    x, y = np.array(xs), np.array(ys)
    d = np.zeros(x.shape)
    count = np.zeros((24, 24), int)
    for i in range(len(x)):
        t, _ = rasterize(x[i:i + 1], y[i:i + 1], d[i:i + 1], 24, 24)
        count += t >= 0
    assert count.max() == 1
    # Interior centres, including those on shared edges, are covered once.
    assert (count[1:20, 1:20] == 1).all()
