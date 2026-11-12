"""Land use from the simplified cadastre (ALKIS "Grundrissdaten vereinfacht", layer Nutzung).

It tells road from pavement, rail, water, forest (broadleaf, conifer, mixed), field, meadow,
park, sports ground and cemetery, so the ground can be drawn by what it is instead of guessed
from the photo. Only the land-use polygons and their type are read: never the parcel layers
or any address column.

One GeoPackage per municipality from OpenGeodata.NRW (Bonn: 05314000, 74 MB zipped).
"""

from __future__ import annotations

import sqlite3
import zipfile
from pathlib import Path

import numpy as np
import shapely

from . import fetch
from .projection import SUBPIXEL
from .rasterize import rasterize

DIRECTORY = "lk/akt/gru_vereinfacht_gpkg/"
LICENCE = "dl-de/zero-2-0 (confirm from metadata)"

# Classes in the `sub` layer of ground pixels.
NONE, BUILT, ROAD, VERGE, PATH, SQUARE, PARKING, RAIL, WATER = 0, 1, 2, 3, 4, 5, 6, 7, 8
FOREST, CONIFER, MIXED, FIELD, MEADOW, PARK, SPORTS, CEMETERY, BARE = 9, 10, 11, 12, 13, 14, 15, 16, 17
NAMES = {NONE: "none", BUILT: "built", ROAD: "road", VERGE: "verge", PATH: "path", SQUARE: "square",
         PARKING: "parking", RAIL: "rail", WATER: "water", FOREST: "forest", CONIFER: "conifer forest",
         MIXED: "mixed forest", FIELD: "field", MEADOW: "meadow", PARK: "park", SPORTS: "sports",
         CEMETERY: "cemetery", BARE: "bare"}
FOREST_CLASSES = (FOREST, CONIFER, MIXED)


def classify(nutzart: str, bez: str | None) -> int:
    """Map ALKIS land use (type and designation) to a ground class."""
    bez = bez or ""
    if nutzart == "Straßenverkehr":
        return VERGE if "Begleitfläche" in bez else ROAD
    if nutzart == "Weg":
        return VERGE if "Begleitfläche" in bez else PATH
    if nutzart == "Platz":
        return PARKING if "Parkplatz" in bez else SQUARE
    if nutzart in ("Bahnverkehr", "Flugverkehr"):
        return RAIL if nutzart == "Bahnverkehr" else SQUARE
    if nutzart in ("Fließgewässer", "Stehendes Gewässer", "Schiffsverkehr", "Hafenbecken", "Meer"):
        return WATER
    if nutzart == "Wald":
        return CONIFER if bez == "Nadelholz" else (MIXED if "Nadel" in bez else FOREST)
    if nutzart == "Gehölz":
        return FOREST
    if nutzart == "Landwirtschaft":
        return FIELD if bez in ("Ackerland", "Gartenland", "Obstplantage", "Baumschule", "Weingarten") else MEADOW
    if nutzart == "Sport-, Freizeit- und Erholungsfläche":
        return SPORTS if bez in ("Sportanlage", "Spielplatz, Bolzplatz", "Golfplatz") else PARK
    if nutzart == "Friedhof":
        return CEMETERY
    if nutzart in ("Unland/Vegetationslose Fläche", "Tagebau, Grube, Steinbruch", "Heide", "Moor", "Sumpf", "Halde"):
        return BARE
    return BUILT


def _gpkg_wkb(blob: bytes) -> bytes:
    """Strip a GeoPackage geometry header, leaving standard WKB."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry")
    flags = blob[3]
    env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    return blob[8 + env:]


def load(data_dir: Path, key: str = "05314000") -> tuple[np.ndarray, np.ndarray]:
    """Land-use polygons and their classes for one municipality (cached as WKB)."""
    cache = data_dir / "gru" / f"landuse_{key}.npz"
    if cache.exists():
        with np.load(cache, allow_pickle=False) as z:
            return shapely.from_wkb(z["wkb"]), z["cls"]
    gpkg = _gpkg_path(data_dir, key)
    con = sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)
    wkbs, classes = [], []
    for blob, nutzart, bez in con.execute("SELECT geometrie, nutzart, bez FROM Nutzung"):
        if blob is None:
            continue
        wkbs.append(_gpkg_wkb(blob))
        classes.append(classify(nutzart or "", bez))
    con.close()
    wkb = np.array(wkbs, dtype=object)
    cls = np.array(classes, dtype=np.uint8)
    cache.parent.mkdir(parents=True, exist_ok=True)
    np.savez(cache, wkb=np.array([bytes(w) for w in wkb], dtype=object).astype("S"), cls=cls)
    return shapely.from_wkb(wkb), cls


def _gpkg_path(data_dir: Path, key: str) -> Path:
    out = data_dir / "gru"
    found = sorted(out.glob(f"gru_vereinf_{key}_*.gpkg"))
    if found:
        return found[0]
    import json
    idx = json.loads(fetch._get(fetch.BASE + DIRECTORY + "index.json"))
    files = {f["name"]: int(f["size"]) for d in idx["datasets"] for f in d["files"]}
    name = next(n for n in files if n.startswith(f"gru_vereinf_{key}_"))
    z = fetch.download(fetch.BASE + DIRECTORY + name, data_dir / "raw" / "gru" / name, files[name])
    fetch.record(data_dir, z, "gru", fetch.BASE + DIRECTORY + name, LICENCE)
    zipfile.ZipFile(z).extractall(out)
    return sorted(out.glob(f"gru_vereinf_{key}_*.gpkg"))[0]


def raster(polys, cls, e0: float, n0: float, res: float, shape) -> np.ndarray:
    """Class of each cell centre of a north-up grid (NONE outside every polygon)."""
    rows, cols = shape
    box = shapely.box(e0, n0 - rows * res, e0 + cols * res, n0)
    tree = shapely.STRtree(polys)
    idx = tree.query(box, predicate="intersects")
    out = np.zeros(shape, dtype=np.uint8)
    if len(idx) == 0:
        return out
    clipped = shapely.intersection(polys[idx], box.buffer(2 * res))
    parts, src = shapely.get_parts(clipped, return_index=True)
    is_poly = shapely.get_type_id(parts) == 3
    parts, src = parts[is_poly], src[is_poly]
    if len(parts) == 0:
        return out
    tris = shapely.constrained_delaunay_triangles(parts)
    tparts, tsrc = shapely.get_parts(tris, return_index=True)
    xy = shapely.get_coordinates(tparts).reshape(len(tparts), 4, 2)[:, :3]
    x = np.rint((xy[:, :, 0] - e0) / res * SUBPIXEL).astype(np.int64)
    y = np.rint((n0 - xy[:, :, 1]) / res * SUBPIXEL).astype(np.int64)
    t, _ = rasterize(x, y, np.zeros(x.shape), cols, rows)
    hit = t >= 0
    out[hit] = cls[idx[src[tsrc[t[hit]]]]]
    return out


def summary(data_dir: Path) -> dict[str, int]:
    _, cls = load(data_dir)
    return {NAMES[int(c)]: int((cls == c).sum()) for c in np.unique(cls)}


__all__ = ["load", "raster", "classify", "NAMES"]
