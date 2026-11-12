"""Land use, tree crowns and cars: the rules behind the detailed map."""

import numpy as np
import yaml

from isometric_bonn import cars, landuse, trees
from isometric_bonn.cli import ROOT

CFG = yaml.safe_load((ROOT / "style" / "style.yaml").read_text())["render"]


def test_land_use_classes():
    assert landuse.classify("Straßenverkehr", "Begleitfläche Straßenverkehr") == landuse.VERGE
    assert landuse.classify("Straßenverkehr", None) == landuse.ROAD
    assert landuse.classify("Wald", "Nadelholz") == landuse.CONIFER
    assert landuse.classify("Wald", "Laub- und Nadelholz") == landuse.MIXED
    assert landuse.classify("Wald", "Laubholz") == landuse.FOREST
    assert landuse.classify("Fließgewässer", "Bach") == landuse.WATER
    assert landuse.classify("Platz", "Parkplatz") == landuse.PARKING
    assert landuse.classify("Wohnbaufläche", None) == landuse.BUILT


def test_geopackage_geometry_header_is_stripped():
    import shapely
    wkb = shapely.to_wkb(shapely.box(0, 0, 1, 1))
    blob = b"GP\x00\x03" + (25832).to_bytes(4, "little") + bytes(32) + wkb  # envelope [minx maxx miny maxy]
    assert shapely.from_wkb(landuse._gpkg_wkb(blob)).equals(shapely.box(0, 0, 1, 1))


def test_two_trees_become_two_crowns():
    yy, xx = np.mgrid[0:60, 0:80]
    h = np.maximum(15 - 0.15 * ((yy - 30) ** 2 + (xx - 22) ** 2) ** 0.5 * 2,
                   12 - 0.15 * ((yy - 30) ** 2 + (xx - 58) ** 2) ** 0.5 * 2).clip(0)
    veg = h > 2
    h = np.where(veg, h, 0.0)
    out, lab, info = trees.crowns(h, veg, np.zeros_like(h, np.float32), 0.0, 0.0, 0.5, CFG)
    assert len(np.unique(lab[lab > 0])) == 2
    assert sorted(np.round(info["top"][info["top"] > 0])) == [12, 15]
    assert (out[veg] > 0).all() and (out[veg] <= h.max() + 1e-6).all()


def test_a_car_blob_becomes_one_car_facing_along_it():
    hag = np.zeros((40, 40))
    hag[18:22, 10:19] = 1.5  # 2 m x 4.5 m, long axis east-west
    lu = np.full(hag.shape, landuse.ROAD, np.uint8)
    px = np.full(hag.shape + (4,), 200, np.float32)  # bright: a white car
    ee, nn = np.meshgrid(np.arange(40) * 0.5 + 0.25, 100 - (np.arange(40) * 0.5 + 0.25))
    no = np.zeros(hag.shape, bool)
    found = cars.detect(hag, no, no, np.zeros(hag.shape), lu, [landuse.ROAD], px, ee, nn, 0.5, CFG)
    assert len(found) == 1 and found["colour"][0] == cars.WHITE
    assert abs(np.cos(found["heading"][0])) > 0.95  # east-west
    tri, sub = cars.geometry(found, np.array([60.0]))
    assert tri.shape == (20, 3, 3) and (sub == cars.GLASS).sum() == 8
