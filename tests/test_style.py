import numpy as np
import yaml

from isometric_bonn.cli import ROOT
from isometric_bonn.scene import CAR, DECK, GROUND, ROOF, TREE, TRUNK, WALL, WATER
from isometric_bonn.style import LOOKS, Palette, stable_pick, stylise, wall_kind
from isometric_bonn.tiles import halve

STYLE = yaml.safe_load((ROOT / "style" / "style.yaml").read_text())
RAMPS = yaml.safe_load((ROOT / "style" / "palette.yaml").read_text())["ramps"]


def _layers(h=64, w=96, seed=0):
    rng = np.random.default_rng(seed)
    mat = rng.choice([GROUND, TREE, ROOF, WALL, WATER, DECK, TRUNK, CAR], size=(h, w)).astype(np.uint8)
    bld = np.where((mat == ROOF) | (mat == WALL), rng.integers(0, 3, (h, w)), -1).astype(np.int32)
    n = rng.normal(size=(h, w, 3))
    n[..., 2] = np.abs(n[..., 2])
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return {
        "mat": mat, "bld": bld, "normal": n.astype(np.float32),
        "sub": rng.integers(0, 18, (h, w)).astype(np.uint8),
        "mark": rng.random((h, w)) < 0.1,
        "facet": rng.integers(0, 4, (h, w)).astype(np.int32),
        "depth": rng.uniform(0, 50, (h, w)).astype(np.float32),
        "photo": rng.integers(0, 256, (h, w, 4)).astype(np.uint8),
        "shadow": rng.random((h, w)) < 0.3,
        "wall_u": rng.uniform(0, 20, (h, w)).astype(np.float32),
        "wall_h": rng.uniform(0, 15, (h, w)).astype(np.float32),
        "wall_len": np.full((h, w), 20, np.float32),
        "bld_function": np.array(["31001_1000", "31001_3023", "31001_2740"]),
        "bld_height": np.array([12, 20, 5], np.float32),
        "bld_gmlid": np.array(["DENW0A", "DENW0B", "DENW0C"]),
        "bld_roof_rgb": np.array([[120, 120, 125], [150, 110, 100], [200, 210, 215]], np.float32),
        "bld_roof_luma": np.array([120, 118, 208], np.float32),
        "bld_roof_ndvi": np.array([0.0, 0.05, 0.0], np.float32),
        "bld_roof_cells": np.array([100, 100, 100]),
    }


def test_every_pixel_is_a_palette_colour():
    pal = {tuple(c) for c in Palette.from_ramps(RAMPS).rgb}
    meta = {"sun": STYLE["sun"]}
    for look in ("flat", "ramp"):
        img = stylise(_layers(), meta, RAMPS, STYLE["look"], look)
        assert {tuple(c) for c in img.reshape(-1, 3)} <= pal, look
        assert {tuple(c) for c in halve(img).reshape(-1, 3)} <= pal, f"{look}, zoomed out"
    assert "photo" in LOOKS  # the comparison look is posterised photo, not palette art


def test_building_choices_are_stable_and_sensible():
    assert stable_pick("DENW36AL10005ovA", ["a", "b", "c"]) == stable_pick("DENW36AL10005ovA", ["a", "b", "c"])
    assert wall_kind("31001_2740", 6)[0] == "glass"
    assert wall_kind("31001_2463", 3) == ("wall_shed", None)
    assert wall_kind("31001_1100", 12) == ("wall_plaster", "home")
    assert wall_kind("31001_3023", 20) == ("wall_stone", "public")
    assert wall_kind("51009_1610", 4) == ("wall_shed", None)
