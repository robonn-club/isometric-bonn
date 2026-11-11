"""All of Bonn: the city boundary, the windows that cover it, and the run over them.

The boundary is Bonn's polygon in DVG1 (municipality key 05314000). The city is rendered in
windows of 4 x 2 map tiles on the global grid. Each window is rendered with a few pixels of
overlap and cropped, so outlines and filters at its edges match its neighbours exactly.
Ground outside Bonn is left empty and the city's edge gets a one-pixel line, so the map reads
as one piece of land.
"""

from __future__ import annotations

import json
import math
import time
import zipfile
from pathlib import Path

import numpy as np
import shapely

from . import fetch
from .projection import TILE, Camera, tile_index, tile_origin

DVG1_ZIP = "vkg/dvg/dvg1/dvg1_EPSG25832_Shape.zip"
DVG1_SIZE = 22456489
_ZK = math.sqrt(6) / 2


def boundary(data_dir: Path, key: str = "05314000") -> shapely.Polygon:
    """The municipality's polygon from DVG1 (downloaded on first use)."""
    cache = data_dir / "dvg1" / f"gem_{key}.wkb"
    if cache.exists():
        return shapely.from_wkb(cache.read_bytes())
    import shapefile  # pyshp, only needed once

    z = fetch.download(fetch.BASE + DVG1_ZIP, data_dir / "raw" / "dvg1" / Path(DVG1_ZIP).name, DVG1_SIZE)
    out = data_dir / "dvg1"
    out.mkdir(parents=True, exist_ok=True)
    zipfile.ZipFile(z).extractall(out)
    r = shapefile.Reader(str(out / "dvg1gem_nw"))
    names = [f[0] for f in r.fields[1:]]
    for i, rec in enumerate(r.records()):
        if dict(zip(names, rec)).get("KN") == key:
            poly = shapely.geometry.shape(r.shape(i).__geo_interface__)
            cache.write_bytes(shapely.to_wkb(poly))
            return poly
    raise KeyError(f"municipality {key} not in DVG1")


def window_footprint(cam: Camera, ox: int, oy: int, w: int, h: int, zlo: float, zhi: float):
    """Ground region that can appear in a window, for heights between zlo and zhi."""
    p = cam.px_per_m
    pts = []
    for z in (zlo, zhi):
        for sx, sy in ((ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h)):
            v = sx / p
            u = -(2 / p) * (sy + _ZK * p * z)
            pts.append(((u + v) / 2, (u - v) / 2))
    return shapely.convex_hull(shapely.MultiPoint(pts))


def windows(cam: Camera, poly, win=(2048, 1024), zlo=40.0, zhi=200.0):
    """Window origins (on the tile grid) whose ground can show part of the city."""
    e0, n0, e1, n1 = poly.bounds
    xs, ys = [], []
    for e in (e0, e1):
        for n in (n0, n1):
            for z in (zlo, zhi):
                x, y = cam.screen(e, n, z)
                xs.append(float(x))
                ys.append(float(y))
    w, h = win
    x0, y0 = tile_origin(cam)
    gx0 = x0 + math.floor((min(xs) - x0) / w) * w
    gy0 = y0 + math.floor((min(ys) - y0) / h) * h
    shapely.prepare(poly)
    out = []
    for oy in range(gy0, int(max(ys)) + 1, h):
        for ox in range(gx0, int(max(xs)) + 1, w):
            if poly.intersects(window_footprint(cam, ox, oy, w, h, zlo, zhi)):
                out.append((ox, oy))
    return out


def data_tiles(cam: Camera, wins, win, margin_m: float, zlo=40.0, zhi=220.0):
    """1 km data tiles all windows need, with a margin for shadows and tall buildings."""
    tiles = set()
    for ox, oy in wins:
        fp = window_footprint(cam, ox, oy, win[0], win[1], zlo, zhi).buffer(margin_m)
        e0, n0, e1, n1 = fp.bounds
        for e in range(math.floor(e0 / 1000), math.floor(e1 / 1000) + 1):
            for n in range(math.floor(n0 / 1000), math.floor(n1 / 1000) + 1):
                if fp.intersects(shapely.box(e * 1000, n * 1000, e * 1000 + 1000, n * 1000 + 1000)):
                    tiles.add((e, n))
    return sorted(tiles)


def inside_mask(poly, layers: dict, center) -> np.ndarray:
    """True for pixels whose world position lies in the city."""
    world = layers["world"]
    e = world[..., 0].astype(np.float64) + center[0]
    n = world[..., 1].astype(np.float64) + center[1]
    hit = layers["mat"] > 0
    out = np.zeros(hit.shape, dtype=bool)
    out[hit] = shapely.contains_xy(poly, e[hit], n[hit])
    return out


def summary(cam: Camera, poly, win=(2048, 1024), margin_m=60.0):
    wins = windows(cam, poly, win)
    tiles = data_tiles(cam, wins, win, margin_m)
    return wins, tiles


def progress_path(out: Path) -> Path:
    return out / "progress.json"


def load_progress(out: Path) -> dict:
    p = progress_path(out)
    return json.loads(p.read_text()) if p.exists() else {"done": {}}


def save_progress(out: Path, prog: dict) -> None:
    progress_path(out).write_text(json.dumps(prog, indent=1) + "\n")


def tile_name(cam: Camera, x: int, y: int) -> str:
    tx, ty = tile_index(cam, x, y)
    return f"{tx}_{ty}"




# --- the run over all windows ---------------------------------------------------------------

def window_area(name: str, cam: Camera, ox: int, oy: int, w: int, h: int, margin: int) -> dict:
    """Area config for one window, with `margin` px of overlap on every side."""
    p = cam.px_per_m
    v = (ox + w / 2) / p
    u = -(2 / p) * ((oy + h / 2) + _ZK * p * 60.0)
    tx, ty = tile_index(cam, ox, oy)
    return {"name": f"{name}/windows/{tx}_{ty}", "center": [round((u + v) / 2), round((u - v) / 2)],
            "origin_px": [ox - margin, oy - margin], "size_px": [w + 2 * margin, h + 2 * margin]}


def render_window(job: dict):
    """Render, colour and tile one window (runs in its own process)."""
    import shutil

    from . import scene
    from .style import stylise
    from .tiles import save_tile

    t0 = time.time()
    cam = Camera(job["px_per_m"])
    poly = shapely.from_wkb(job["poly"])
    shapely.prepare(poly)
    ox, oy, w, h, m = job["ox"], job["oy"], job["w"], job["h"], job["margin"]
    area = window_area(job["name"], cam, ox, oy, w, h, m)
    out_dir, data_dir = Path(job["out"]), Path(job["data"])
    scene.build_layers(area, job["style"], data_dir, out_dir, log=lambda s: None, clip=poly)
    wdir = out_dir / area["name"]
    layers = dict(np.load(wdir / "layers.npz"))
    meta = json.loads((wdir / "layers.json").read_text())
    written = 0
    for look in job["looks"]:
        img = stylise(layers, meta, job["ramps"], job["style"]["look"], look)
        alpha = np.where(layers["mat"] > 0, 255, 0).astype(np.uint8)
        rgba = np.dstack([img, alpha])[m:m + h, m:m + w]
        for j in range(h // TILE):
            for i in range(w // TILE):
                tx, ty = tile_index(cam, ox + i * TILE, oy + j * TILE)
                tile = rgba[j * TILE:(j + 1) * TILE, i * TILE:(i + 1) * TILE]
                written += save_tile(np.ascontiguousarray(tile),
                                     out_dir / job["name"] / "tiles" / look / "0" / f"{tx}_{ty}.webp")
    if not job["keep_layers"]:
        shutil.rmtree(wdir)
    return f"{ox}_{oy}", {"seconds": round(time.time() - t0, 1), "tiles": written,
                          "buildings": meta["buildings"], "triangles": meta["triangles"]}


def run(area: dict, style: dict, ramps: dict, data_dir: Path, out_root: Path, workers: int = 1,
        looks=("ramp",), keep_layers: bool = True, limit: int | None = None, log=print) -> Path:
    import multiprocessing as mp

    from . import scene
    from .tiles import build_pyramid

    cam = Camera(float(style["camera"]["px_per_m"]))
    poly = boundary(data_dir, area.get("municipality", "05314000"))
    w, h = area.get("window_px", [2048, 1024])
    margin = int(area.get("overlap_px", 4))
    wins = windows(cam, poly, (w, h))
    out = out_root / area["name"]
    out.mkdir(parents=True, exist_ok=True)
    log(f"{area['name']}: {poly.area / 1e6:.2f} km2, {len(wins)} windows of {w}x{h} px")

    need = set()
    for ox, oy in wins:
        need.update(scene.tiles_needed(window_area(area["name"], cam, ox, oy, w, h, margin), style))
    fetch.fetch_tiles(sorted(need), data_dir, log=log)

    prog = load_progress(out)
    todo = [(ox, oy) for ox, oy in wins if f"{ox}_{oy}" not in prog["done"]]
    if limit is not None:
        todo = todo[:limit]
    log(f"{len(prog['done'])} windows done before, {len(todo)} to render with {workers} worker(s)")
    base = {"name": area["name"], "px_per_m": cam.px_per_m, "poly": shapely.to_wkb(poly), "w": w, "h": h,
            "margin": margin, "out": str(out_root), "data": str(data_dir), "style": style, "ramps": ramps,
            "looks": list(looks), "keep_layers": keep_layers}
    jobs = [dict(base, ox=ox, oy=oy) for ox, oy in todo]
    t0 = time.time()
    ctx = mp.get_context("fork")
    with ctx.Pool(workers, maxtasksperchild=1) as pool:
        for i, (key, res) in enumerate(pool.imap_unordered(render_window, jobs), 1):
            prog["done"][key] = res
            save_progress(out, prog)
            rate = (time.time() - t0) / i
            log(f"  {i}/{len(jobs)} window {key}: {res['tiles']} tiles, {res['seconds']} s "
                f"(about {rate * (len(jobs) - i) / 60:.0f} min left)")
    if len(prog["done"]) >= len(wins):
        for look in looks:
            top = build_pyramid(out / "tiles" / look, log=lambda s: log(f"  {look} {s}"))
            log(f"{look}: pyramid of {top + 1} levels")
    return out


# --- labels ----------------------------------------------------------------------------------

def label_points(area: dict, cam: Camera, data_dir: Path) -> list[dict]:
    """Label anchors in level-0 pixels of the Bonn tile grid.

    A label has `lonlat` or `at` (EPSG:25832). With `snap: tallest` it moves to the tallest
    LoD2 building within `radius` metres and sits on its top, so a rough position is enough.
    """
    from . import citygml
    from .fetch import local_file
    from .geo import lonlat_to_utm32
    from .projection import tile_origin
    from .rasters import mosaic

    x0, y0 = tile_origin(cam)
    out = []
    for lab in area.get("labels", []):
        e, n = lab["at"] if "at" in lab else lonlat_to_utm32(*lab["lonlat"])
        up = float(lab.get("up", 0))
        if lab.get("snap") == "tallest":
            t = citygml.load_tile(data_dir, local_file(data_dir, "lod2", int(e // 1000), int(n // 1000)))
            g = t["tri_kind"] == citygml.KIND_GROUND
            c = t["tri"][g].mean(1)
            nb = len(t["bld_gmlid"])
            cnt = np.bincount(t["tri_bld"][g], minlength=nb)
            ce = np.bincount(t["tri_bld"][g], weights=c[:, 0], minlength=nb) / np.maximum(cnt, 1)
            cn = np.bincount(t["tri_bld"][g], weights=c[:, 1], minlength=nb) / np.maximum(cnt, 1)
            near = (cnt > 0) & (np.hypot(ce - e, cn - n) < float(lab.get("radius", 150)))
            if near.any():
                tops = np.full(nb, -np.inf)
                np.maximum.at(tops, t["tri_bld"], t["tri"][:, :, 2].max(1))
                i = int(np.argmax(np.where(near, tops, -np.inf)))
                e, n = float(ce[i]), float(cn[i])
                z = float(tops[i]) + 3
            else:
                z = None
        else:
            z = None
        if z is None:
            z = float(mosaic("dgm1", data_dir, e - 2, n - 2, e + 2, n + 2).bilinear(e, n)) + up
        sx, sy = cam.screen(e, n, z)
        out.append({"name": lab["name"], "x": round(float(sx) - x0), "y": round(float(sy) - y0),
                    "min": float(lab.get("min_scale", 0))})
    return out
