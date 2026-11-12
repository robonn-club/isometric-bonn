"""isobonn: build the isometric map of Bonn, one area at a time.

  isobonn fetch  AREA    download the NRW tiles the area needs (robots.txt first)
  isobonn sun    AREA    estimate the aerial photo's sun from its building shadows
  isobonn render AREA    render data layers to out/AREA/layers.npz (the slow step)
  isobonn style  AREA    colour the layers: images and 512 px tiles for every look
  isobonn demo   AREA    the comparison page in out/AREA/demo/
  isobonn all    AREA    fetch, render, style, demo
  isobonn city   AREA    a whole city (areas/bonn.yaml): every window, the zoom levels and the viewer
  isobonn site   bonn    the public site for GitHub Pages: out/site/ and out/site.tar.gz

AREA is a name in areas/ (e.g. poppelsdorf) or a path to a YAML file.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
OUT = ROOT / "out"


def load_area(arg: str) -> dict:
    path = Path(arg)
    if not path.suffix:
        path = ROOT / "areas" / f"{arg}.yaml"
    return yaml.safe_load(path.read_text())


def load_style() -> tuple[dict, dict]:
    style = yaml.safe_load((ROOT / "style" / "style.yaml").read_text())
    ramps = yaml.safe_load((ROOT / "style" / "palette.yaml").read_text())["ramps"]
    return style, ramps


def cmd_fetch(area, style, ramps, args):
    from . import fetch, scene
    tiles = scene.tiles_needed(area, style)
    print(f"{area['name']}: {len(tiles)} data tiles of 1 km: {tiles}")
    fetch.fetch_tiles(tiles, DATA, log=print)
    print(f"manifest: {DATA / 'manifest.json'}")


def cmd_sun(area, style, ramps, args):
    from . import sun
    (az, el), _ = sun.estimate(area, style, DATA)
    print(f"put this in style/style.yaml under sun:  azimuth: {az}  elevation: {el}")


def cmd_render(area, style, ramps, args):
    from . import scene
    scene.build_layers(area, style, DATA, OUT, log=print)


def cmd_style(area, style, ramps, args):
    from .projection import Camera
    from .style import LOOKS, marks, stylise
    from .tiles import halve, save_png, write_tiles
    out = OUT / area["name"]
    layers = dict(np.load(out / "layers.npz"))
    meta = json.loads((out / "layers.json").read_text())
    cam = Camera(meta["px_per_m"])
    looks = LOOKS if args.look == "all" else (args.look,)
    for look in looks:
        t = time.time()
        img = stylise(layers, meta, ramps, style["look"], look)
        save_png(img, out / f"{look}.png")
        save_png(halve(img, keep=marks(ramps)), out / f"{look}-half.png")
        tiles = write_tiles(img, cam, tuple(meta["origin_px"]), out / "tiles" / look)
        colours = len(np.unique(img.reshape(-1, 3), axis=0))
        print(f"{look}: {out / (look + '.png')}, {len(tiles)} tiles, {colours} colours ({time.time() - t:.1f} s)")


def cmd_demo(area, style, ramps, args):
    from .demo import build_demo
    path = build_demo(area, style, ramps, ROOT, OUT / area["name"])
    print(f"demo: {path}")


def cmd_city(area, style, ramps, args):
    from .city import run
    from .demo import build_city_viewer
    out = run(area, style, ramps, DATA, OUT, workers=args.workers, keep_layers=not args.drop_layers,
              limit=args.limit, log=print)
    from .city import load_progress, windows, boundary
    from .projection import Camera
    cam = Camera(float(style["camera"]["px_per_m"]))
    total = len(windows(cam, boundary(DATA, area.get("municipality", "05314000")), tuple(area.get("window_px", [2048, 1024]))))
    if len(load_progress(out)["done"]) < total:
        print(f"{len(load_progress(out)['done'])} of {total} windows done; run again to continue")
        return
    res = build_city_viewer(area, style, ROOT, out)
    print(f"viewer: {res['viewer']}")
    print(f"preview: {res['preview']} ({res['sheets']} sheets, {res['sheet_mb']:.0f} MB)")


def cmd_site(area, style, ramps, args):
    from .demo import build_site
    build_site(ROOT, OUT)


def cmd_all(area, style, ramps, args):
    args.look = "all"
    for step in (cmd_fetch, cmd_render, cmd_style, cmd_demo):
        step(area, style, ramps, args)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="isobonn", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["fetch", "sun", "render", "style", "demo", "all", "city", "site"])
    ap.add_argument("area")
    ap.add_argument("--look", default="all", help="flat, ramp, photo or all (style only)")
    ap.add_argument("--workers", type=int, default=1, help="city: windows rendered in parallel (about 3.5 GB each)")
    ap.add_argument("--limit", type=int, default=None, help="city: render at most this many windows now")
    ap.add_argument("--drop-layers", action="store_true", help="city: delete each window's layers after tiling")
    args = ap.parse_args(argv)
    area = load_area(args.area)
    style, ramps = load_style()
    globals()[f"cmd_{args.command}"](area, style, ramps, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
