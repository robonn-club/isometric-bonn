"""The plan's seam test on real data: one tile rendered alone equals the same tile cut
from a larger window. Needs the Poppelsdorf data (isobonn fetch poppelsdorf); slow."""

import json

import numpy as np
import pytest
import yaml

from isometric_bonn import scene
from isometric_bonn.cli import DATA, OUT, ROOT
from isometric_bonn.style import stylise

AREA = yaml.safe_load((ROOT / "areas" / "poppelsdorf.yaml").read_text())
STYLE = yaml.safe_load((ROOT / "style" / "style.yaml").read_text())
RAMPS = yaml.safe_load((ROOT / "style" / "palette.yaml").read_text())["ramps"]
FULL = OUT / "poppelsdorf"

pytestmark = pytest.mark.skipif(
    not (DATA / "manifest.json").exists() or not (FULL / "layers.npz").exists(),
    reason="needs fetched data and a rendered poppelsdorf window",
)


def test_one_tile_alone_matches_the_window(tmp_path):
    meta = json.loads((FULL / "layers.json").read_text())
    ox, oy = meta["origin_px"]
    i, j = 2, 0  # the tile with Poppelsdorfer Schloss
    tile = dict(AREA, name="seam", size_px=[512, 512], origin_px=[ox + 512 * i, oy + 512 * j])
    scene.build_layers(tile, STYLE, DATA, tmp_path, log=lambda s: None)
    a = dict(np.load(tmp_path / "seam" / "layers.npz"))
    b = dict(np.load(FULL / "layers.npz"))
    sl = (slice(512 * j, 512 * j + 512), slice(512 * i, 512 * i + 512))
    for k in ("mat", "depth", "shadow", "photo"):
        assert np.array_equal(a[k], b[k][sl]), k
    # Same buildings at the same pixels (indices differ, so compare their IDs).
    ida = np.where(a["bld"] >= 0, a["bld_gmlid"][np.maximum(a["bld"], 0)], "")
    idb = np.where(b["bld"][sl] >= 0, b["bld_gmlid"][np.maximum(b["bld"][sl], 0)], "")
    assert np.array_equal(ida, idb)
    # Styled pixels agree away from the 2 px border (outlines and filters look 1 px out).
    meta_a = json.loads((tmp_path / "seam" / "layers.json").read_text())
    img_a = stylise(a, meta_a, RAMPS, STYLE["look"], "ramp")
    img_b = stylise(b, meta, RAMPS, STYLE["look"], "ramp")[sl]
    assert np.array_equal(img_a[2:-2, 2:-2], img_b[2:-2, 2:-2])


def _city_window(tmp_path, ox, oy, poly, m=4):
    from isometric_bonn import city
    from isometric_bonn.projection import Camera
    cam = Camera(float(STYLE["camera"]["px_per_m"]))
    area = city.window_area("seam-city", cam, ox, oy, 2048, 1024, m)
    scene.build_layers(area, STYLE, DATA, tmp_path, log=lambda s: None, clip=poly)
    lay = dict(np.load(tmp_path / area["name"] / "layers.npz"))
    meta = json.loads((tmp_path / area["name"] / "layers.json").read_text())
    img = stylise(lay, meta, RAMPS, STYLE["look"], "ramp")
    alpha = np.where(lay["mat"] > 0, 255, 0).astype(np.uint8)
    return np.dstack([img, alpha])[m:m + 1024, m:m + 2048]


@pytest.mark.skipif(not (DATA / "dvg1").exists(), reason="needs the Bonn boundary (isobonn city bonn)")
def test_city_windows_agree_across_their_borders(tmp_path):
    """Two overlapping city windows, one shifted by half its width, agree where they overlap,
    including the boundary clip and the cropped overlap."""
    from isometric_bonn import city
    from isometric_bonn.projection import Camera
    from isometric_bonn.geo import lonlat_to_utm32
    cam = Camera(float(STYLE["camera"]["px_per_m"]))
    poly = city.boundary(DATA)
    wins = city.windows(cam, poly)
    mx, my = cam.screen(*lonlat_to_utm32(7.1022, 50.7353), 60)  # the Markt
    zentrum = min(wins, key=lambda w: abs(w[0] + 1024 - float(mx)) + abs(w[1] + 512 - float(my)))
    ox, oy = zentrum
    try:
        a = _city_window(tmp_path, ox, oy, poly)
        b = _city_window(tmp_path, ox + 1024, oy, poly)
    except FileNotFoundError as e:
        pytest.skip(f"data not downloaded yet: {e}")
    assert np.array_equal(a[:, 1024:], b[:, :1024])
