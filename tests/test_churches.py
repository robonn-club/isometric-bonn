"""Churches: towers LoD2 lacks come back from the height model, and crosses sit on top."""

import numpy as np
import yaml
from pathlib import Path

from isometric_bonn import churches, citygml
from isometric_bonn.rasters import Grid
from isometric_bonn.style import CROSS, Palette, _crosses, marks, wall_kind
from isometric_bonn.tiles import halve

ROOT = Path(__file__).resolve().parents[1]
CFG = yaml.safe_load((ROOT / "style" / "style.yaml").read_text())["render"]


def _box(e0, n0, e1, n1, z):
    """Two horizontal triangles covering a rectangle at height z."""
    a, b, c, d = (e0, n0, z), (e1, n0, z), (e1, n1, z), (e0, n1, z)
    return np.array([[a, b, c], [a, c, d]], dtype=np.float64)


def _church(nir_tower=60.0, lod2_tower_top=None):
    """A 20 x 12 m church, ground at 50 m, flat LoD2 roof at 65 m. The height model has a
    6 x 6 m tower whose walls end 30 m above ground and whose spire reaches 50 m."""
    ground = _box(1000, 2000, 1020, 2012, 50.0)
    roofs = _box(1000, 2000, 1020, 2012, 65.0)
    if lod2_tower_top is not None:
        roofs = np.concatenate([roofs, _box(1002, 2003, 1008, 2009, lod2_tower_top)])
    res = 0.5
    e0, n0 = 995.0, 2017.0
    rows, cols = int(22 / res), int(30 / res)
    rr, cc = np.mgrid[0:rows, 0:cols]
    e, n = e0 + (cc + 0.5) * res, n0 - (rr + 0.5) * res
    ndom = np.zeros((rows, cols), np.float32)
    ndom[(e > 1000) & (e < 1020) & (n > 2000) & (n < 2012)] = 15.0
    tower = (e > 1002) & (e < 1008) & (n > 2003) & (n < 2009)
    ndom[tower] = 30.0
    d = np.maximum(np.abs(e - 1005), np.abs(n - 2006))  # Chebyshev distance from the axis
    spire = tower & (d < 1.5)
    ndom[spire] = 30.0 + 20.0 * (1 - d[spire] / 1.5)
    nd = Grid(ndom, e0, n0, res)
    dg = Grid(np.full((30, 40), 50.0, np.float32), 990.0, 2020.0, 1.0)
    photo = np.zeros((60, 80, 4), np.uint8)
    photo[...] = (100, 100, 100, 60)  # roof: reflects little infrared
    dop = Grid(photo, 990.0, 2020.0, 0.5)
    if nir_tower != 60.0:
        pr, pc = np.mgrid[0:60, 0:80]
        pe, pn = 990.0 + (pc + 0.5) * 0.5, 2020.0 - (pr + 0.5) * 0.5
        green = (pe > 1002) & (pe < 1008) & (pn > 2003) & (pn < 2009)
        photo[green, 3] = nir_tower
    return ground, roofs, nd, dg, dop


def test_church_codes():
    assert churches.is_church("31001_3041") and churches.is_church("31001_3043")
    assert not churches.is_church("31001_3042")  # synagogue: keeps the normal look
    assert not churches.is_church("31001_1000") and not churches.is_church("51009_1610")
    assert wall_kind("31001_3041", 20.0) == ("wall_church", "church")


def test_missing_tower_comes_back():
    ground, roofs, nd, dg, dop = _church()
    found = churches.find_towers(ground, roofs, nd, dg, dop, CFG)
    assert found is not None
    tris, kinds, faces, normals = found
    assert len(tris) == 14  # 4 walls, a flat top and a 4-sided spire
    walls = tris[kinds == citygml.KIND_WALL]
    eave = walls[..., 2].max()
    apex = tris[..., 2].max()
    assert abs(eave - 80.0) < 1.5, eave  # walls end 30 m above ground
    assert abs(apex - (50.0 + nd.data.max())) < 1e-3, apex  # the highest sample of the height model
    side = np.linalg.norm(walls[0, 0, :2] - walls[0, 1, :2])
    assert 5.0 < side < 7.0, side
    # Walls face outwards, roofs face up.
    assert (normals[kinds == citygml.KIND_ROOF][:, 2] > 0).all()
    centre = np.array([1005.0, 2006.0])
    out = walls.mean(1)[:, :2] - centre
    assert ((normals[kinds == citygml.KIND_WALL][:, :2] * out).sum(1) > 0).all()


def test_tree_over_a_church_is_no_tower():
    ground, roofs, nd, dg, dop = _church(nir_tower=200.0)
    assert churches.find_towers(ground, roofs, nd, dg, dop, CFG) is None


def test_tower_already_in_lod2_adds_nothing():
    ground, roofs, nd, dg, dop = _church(lod2_tower_top=101.0)
    assert churches.find_towers(ground, roofs, nd, dg, dop, CFG) is None


def _bld(gid, fn, e0, n0, e1, n1, top):
    """A flat-roofed building on ground at 50 m."""
    roof = _box(e0, n0, e1, n1, top)
    return {"gid": gid, "fn": fn, "ground": _box(e0, n0, e1, n1, 50.0), "roofs": roof, "upper": roof}


def _towers(*specs):
    """Restored towers as find_towers returns them: (centre e, centre n, tip) each, 6 m wide."""
    u, v = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    parts = [churches._tower_mesh(np.array([e, n]), u, v, 3.0, 3.0, 50.0, 80.0, tip, 1.5) for e, n, tip in specs]
    faces = np.concatenate([f + 9 * i for i, (_, _, f) in enumerate(parts)])
    normals = np.concatenate([churches._normals(t, (e, n)) for (t, _, _), (e, n, _) in zip(parts, specs)])
    return np.concatenate([t for t, _, _ in parts]), np.concatenate([k for _, k, _ in parts]), faces, normals


def test_one_cross_per_complex():
    blds = [_bld("a", 3041, 0, 0, 30, 12, 65.0),      # nave, 15 m
            _bld("b", 3040, 35, 0, 41, 6, 80.0),      # its freestanding bell tower, 5 m away, 30 m
            _bld("c", 3048, -20, 0, -5, 12, 64.0),    # a monastery wing on the other side
            _bld("d", 3041, 100, 0, 120, 12, 64.0),   # another church, 59 m away
            _bld("e", 3043, 200, 0, 203, 3, 55.0)]    # a wayside shrine, too small for a cross
    picks = churches.place_crosses(blds, [None] * len(blds), CFG)
    assert sorted(i for i, _, _ in picks) == [1, 3]
    assert {i: float(p[2]) for i, p, _ in picks}[1] == 80.0  # on the bell tower, the highest point


def test_twin_towers_keep_both_crosses():
    church = _bld("t", 3041, 0, 0, 30, 14, 70.0)
    twins = churches.place_crosses([church], [_towers((4, 4, 95.5), (4, 10, 95.3))], CFG)
    assert sorted(round(float(p[2]), 1) for _, p, _ in twins) == [95.3, 95.5]
    unequal = churches.place_crosses([church], [_towers((4, 4, 95.5), (4, 10, 90.0))], CFG)
    assert [round(float(p[2]), 1) for _, p, _ in unequal] == [95.5]


def _table():
    tris, kinds, faces, normals = _towers((5, 5, 30.0))
    return {"tower_gid": np.array(["y", "z"]), "tower_owner": np.repeat(np.arange(2, dtype=np.int32), 14),
            "tower_tri": np.concatenate([tris, tris]), "tower_kind": np.concatenate([kinds, kinds]),
            "tower_normal": np.concatenate([normals, normals]), "tower_poly": -2 - np.r_[faces, faces + 9],
            "cross_gid": np.array(["z", "y"]), "cross_xyz": np.array([[0.0, 0.0, 1.0], [5.0, 5.0, 30.0]]),
            "cross_slope": np.array([1.0, 0.1])}


def test_table_joins_the_window_buildings(tmp_path):
    b = {"bld_gmlid": np.array(["x", "y"]), "tri": _box(0, 0, 1, 1, 0.0), "tri_bld": np.array([0, 1], np.int32),
         "tri_kind": np.full(2, citygml.KIND_ROOF, np.uint8), "tri_normal": np.zeros((2, 3), np.float32),
         "tri_poly": np.array([0, 1], np.int64)}
    churches.save(_table(), tmp_path / "churches.npz")
    tab = churches.load(tmp_path / "churches.npz")
    out, crosses = churches.apply(b, tab)
    assert len(out["tri"]) == 2 + 14  # only y's tower: z is not in this window
    assert (out["tri_bld"][2:] == 1).all() and (out["tri_poly"][2:] < -1).all()
    assert out["tri_normal"].dtype == np.float32
    assert crosses["bld"].tolist() == [1] and crosses["xyz"][0, 2] == 30.0


def test_cross_drawn_unless_hidden():
    ramps = yaml.safe_load((ROOT / "style" / "palette.yaml").read_text())["ramps"]
    pal = Palette.from_ramps(ramps)
    h, w = 40, 40
    ramp = np.full((h, w), pal.rid("background"), np.int16)
    step = np.zeros((h, w), np.int16)
    depth = np.full((h, w), np.inf, np.float32)
    depth[:, :18] = -10.0  # something in front covers the left part
    layers = {"cross_xy": np.array([[20, 30]]), "cross_depth": np.array([0.0], np.float32),
              "cross_rod": np.array([[20, 3]]), "depth": depth}
    _crosses(layers, ramp, step, pal)
    gold = ramp == pal.rid("gold")
    drawn = {(x, y) for y, x in zip(*np.nonzero(gold))}
    expect = {(20 + dx, 30 + dy) for dx, dy, k in CROSS if k > 0 and 20 + dx >= 18}
    assert drawn == expect
    assert not gold[:, :18].any()  # hidden behind the thing in front
    assert (ramp[30:33, 20] == pal.rid("outline")).all()  # the rod down to the spire


def test_cross_survives_zooming_out():
    ramps = yaml.safe_load((ROOT / "style" / "palette.yaml").read_text())["ramps"]
    gold = marks(ramps)
    assert gold[0] == (0xF2, 0xCF, 0x62)  # the lit gold comes first
    img = np.full((8, 8, 4), (90, 90, 90, 255), np.uint8)
    img[3, 4, :3] = gold[1]  # one shaded gold pixel among grey
    img[6, 6, :3] = gold[1]
    img[6, 7, :3] = gold[0]
    out = halve(img, keep=gold)
    assert tuple(out[1, 2]) == (*gold[1], 255)
    assert tuple(out[3, 3]) == (*gold[0], 255)  # the brighter gold wins a mixed block
    assert (halve(img)[..., :3] == 90).all()  # by plain majority the grey would win
