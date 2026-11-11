"""The comparison page for an area: out/<area>/demo/.

The page template is viewer/demo.html. Its {{placeholders}} are filled with the area's
numbers, label positions and the two self-hosted fonts (inlined, so the page makes no
third-party requests). Two files come out: index.html to open locally, and page.html,
the same content without the document wrapper, for publishing as a preview.
"""

from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path

import numpy as np
from PIL import Image

from .projection import Camera
from .rasters import mosaic

IMAGES = ("ramp", "flat", "photo")


def _font(path: Path) -> str:
    return "data:font/woff2;base64," + base64.b64encode(path.read_bytes()).decode()


def build_demo(area: dict, style: dict, ramps: dict, root: Path, out: Path) -> Path:
    meta = json.loads((out / "layers.json").read_text())
    cam = Camera(meta["px_per_m"])
    ox, oy = meta["origin_px"]
    data = root / "data"
    labels = []
    for lab in area.get("labels", []):
        e, n = lab["at"]
        z = float(mosaic("dgm1", data, e - 2, n - 2, e + 2, n + 2).bilinear(e, n)) + lab.get("up", 0)
        x, y = cam.screen(e, n, z)
        labels.append({"name": lab["name"], "x": round(float(x) - ox), "y": round(float(y) - oy)})

    demo = out / "demo"
    demo.mkdir(parents=True, exist_ok=True)
    for look in IMAGES:
        for suffix in ("", "-half"):
            shutil.copy(out / f"{look}{suffix}.png", demo / f"{look}{suffix}.png")
    ramp = np.asarray(Image.open(out / "ramp.png").convert("RGB"))
    tiles = sorted((out / "tiles" / "ramp").glob("*.webp"))
    tile_kb = sum(p.stat().st_size for p in tiles) / max(len(tiles), 1) / 1024
    manifest = json.loads((data / "manifest.json").read_text())
    data_mb = sum(f["size"] for f in manifest["files"].values()) / 1e6

    w, h = meta["size_px"]
    values = {
        "title": area.get("title", area["name"]),
        "width": w, "height": h,
        "area_km2": f"{w * h / (cam.px_per_m ** 2) / 1e6:.2f}".rstrip("0").rstrip("."),
        "px_per_m": f"{cam.px_per_m:g}",
        "metres_per_px": f"{1 / cam.px_per_m:g}",
        "buildings": f"{meta['buildings']:,}",
        "triangles": f"{meta['triangles'] / 1e6:.1f}",
        "render_s": f"{meta['render_seconds']:.0f}",
        "colours": len(np.unique(ramp.reshape(-1, 3), axis=0)),
        "palette": sum(len(v) for v in ramps.values()),
        "tiles": len(tiles), "tile_kb": f"{tile_kb:.0f}",
        "bonn_mb": f"{2150 * 4 / 3 * tile_kb / 1024:.0f}",
        "data_files": len(manifest["files"]), "data_mb": f"{data_mb:.0f}",
        "sun_az": f"{style['sun']['azimuth']:g}", "sun_el": f"{style['sun']['elevation']:g}",
        "labels": json.dumps(labels, ensure_ascii=False),
        "font_display": _font(root / "viewer" / "fonts" / "outfit-var.woff2"),
        "font_body": _font(root / "viewer" / "fonts" / "manrope-var.woff2"),
    }
    page = (root / "viewer" / "demo.html").read_text()
    for k, v in values.items():
        page = page.replace("{{" + k + "}}", str(v))
    if "{{" in page:
        raise ValueError("unfilled placeholder in viewer/demo.html: " + page[page.index("{{"):][:40])
    (demo / "page.html").write_text(page)
    doc = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
           '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
           '</head>\n<body>\n' + page + '\n</body>\n</html>\n')
    (demo / "index.html").write_text(doc)
    return demo / "index.html"


def _fill(template: str, values: dict) -> str:
    for k, v in values.items():
        template = template.replace("{{" + k + "}}", str(v))
    if "{{" in template:
        raise ValueError("unfilled placeholder: " + template[template.index("{{"):][:40])
    return template


def _wrap(page: str) -> str:
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            '</head>\n<body>\n' + page + '\n</body>\n</html>\n')


def city_buildings(data_dir: Path, poly, tiles) -> int:
    """Buildings whose footprint centre lies in the city (counted once, from LoD2)."""
    import shapely

    from . import citygml
    from .fetch import local_file
    seen = set()
    for te, tn in tiles:
        try:
            t = citygml.load_tile(data_dir, local_file(data_dir, "lod2", te, tn))
        except FileNotFoundError:
            continue
        g = t["tri_kind"] == citygml.KIND_GROUND
        nb = len(t["bld_gmlid"])
        c = t["tri"][g].mean(1)
        cnt = np.bincount(t["tri_bld"][g], minlength=nb)
        ce = np.bincount(t["tri_bld"][g], weights=c[:, 0], minlength=nb) / np.maximum(cnt, 1)
        cn = np.bincount(t["tri_bld"][g], weights=c[:, 1], minlength=nb) / np.maximum(cnt, 1)
        inside = (cnt > 0) & shapely.contains_xy(poly, ce, cn)
        seen.update(t["bld_gmlid"][inside].tolist())
    return len(seen)


def build_city_viewer(area: dict, style: dict, root: Path, out: Path, look: str = "ramp",
                      pack_preview: bool = True) -> dict:
    """The city viewer: out/<area>/viewer/index.html over the 512 px tiles, and
    out/<area>/preview/page.html over 2048 px sheets (fewer files, for a hosted preview)."""
    import datetime as dt

    from . import city
    from .projection import TILE, Camera
    from .tiles import pack, tile_names

    data = root / "data"
    cam = Camera(float(style["camera"]["px_per_m"]))
    poly = city.boundary(data, area.get("municipality", "05314000"))
    tiles_root = out / "tiles" / look
    levels = {int(d.name): sorted(tile_names(d)) for d in tiles_root.iterdir() if d.name.isdigit()}
    xs = [x for x, _ in levels[0]]
    ys = [y for _, y in levels[0]]
    bounds = [min(xs) * TILE, min(ys) * TILE, (max(xs) + 1) * TILE, (max(ys) + 1) * TILE]
    labels = city.label_points(area, cam, data)
    start_label = next((lab for lab in labels if lab["name"] == "Zentrum"), labels[0] if labels else None)
    start = {"x": start_label["x"] if start_label else (bounds[0] + bounds[2]) // 2,
             "y": start_label["y"] + 300 if start_label else (bounds[1] + bounds[3]) // 2, "scale": 0.5}
    prog = city.load_progress(out)
    wins = prog["done"]
    manifest = json.loads((data / "manifest.json").read_text())
    lod2 = [(int(n.split("_")[2]), int(n.split("_")[3])) for n, f in manifest["files"].items() if f["product"] == "lod2"]
    size = sum(f.stat().st_size for f in tiles_root.rglob("*.webp"))
    values = {
        "area_km2": f"{poly.area / 1e6:.0f}",
        "buildings": f"{city_buildings(data, poly, lod2):,}",
        "windows": len(wins),
        "hours": f"{sum(w['seconds'] for w in wins.values()) / 3600:.1f}",
        "tiles": f"{len(levels[0]):,}",
        "size_mb": f"{size / 1e6:.0f}",
        "data_gb": f"{sum(f['size'] for f in manifest['files'].values()) / 1e9:.1f}",
        "date": dt.date.today().isoformat(),
        "labels": json.dumps(labels, ensure_ascii=False),
        "bounds": json.dumps(bounds),
        "start": json.dumps(start),
        "px_per_m": f"{cam.px_per_m:g}",
        "font_display": _font(root / "viewer" / "fonts" / "outfit-var.woff2"),
        "font_body": _font(root / "viewer" / "fonts" / "manrope-var.woff2"),
    }
    template = (root / "viewer" / "city.html").read_text()

    local = dict(values, tile_px=TILE, url=f"../tiles/{look}/{{z}}/{{x}}_{{y}}.webp",
                 levels=json.dumps({str(k): [f"{x}_{y}" for x, y in v] for k, v in levels.items()}))
    (out / "viewer").mkdir(parents=True, exist_ok=True)
    (out / "viewer" / "index.html").write_text(_wrap(_fill(template, local)))

    if not pack_preview:
        return {"viewer": out / "viewer" / "index.html", "values": values}
    sheets = pack(tiles_root, out / "preview" / "pack")
    prev = dict(values, tile_px=TILE * 4, url="pack/{z}/{x}_{y}.webp",
                levels=json.dumps({str(k): [f"{x}_{y}" for x, y in v] for k, v in sheets.items()}))
    (out / "preview" / "page.html").write_text(_fill(template, prev))
    (out / "preview" / "index.html").write_text(_wrap(_fill(template, prev)))
    files = sorted((out / "preview" / "pack").rglob("*.webp"))
    return {"viewer": out / "viewer" / "index.html", "preview": out / "preview" / "page.html",
            "sheets": len(files), "sheet_mb": sum(f.stat().st_size for f in files) / 1e6, "values": values}


def build_site(root: Path, out_root: Path, look: str = "ramp", limit_mb: float = 1000) -> Path:
    """The public site, ready for GitHub Pages: out/site/ and out/site.tar.gz.

    index.html is the city viewer over the 512 px tiles in tiles/, and poppelsdorf/ holds the
    comparison page. Everything is relative, so the site works under any path, such as
    https://robonn-club.github.io/isometric-bonn/. The archive goes into a GitHub Release;
    .github/workflows/pages.yml deploys it. Tiles never enter git.
    """
    import os
    import tarfile

    import yaml

    style = yaml.safe_load((root / "style" / "style.yaml").read_text())
    area = yaml.safe_load((root / "areas" / "bonn.yaml").read_text())
    city_out = out_root / area["name"]
    site = out_root / "site"
    if site.exists():
        shutil.rmtree(site)
    (site / "poppelsdorf").mkdir(parents=True)

    # Tiles: hard links when possible (same disk, no extra space), copies otherwise.
    src = city_out / "tiles" / look
    for f in src.rglob("*.webp"):
        dst = site / "tiles" / f.relative_to(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(f, dst)
        except OSError:
            shutil.copy2(f, dst)

    # The city page, pointing at tiles/ and linking the comparison page.
    res = build_city_viewer(area, style, root, city_out, look=look, pack_preview=False)
    page = (city_out / "viewer" / "index.html").read_text()
    page = page.replace(f"../tiles/{look}/{{z}}/{{x}}_{{y}}.webp", "tiles/{z}/{x}_{y}.webp")
    page = page.replace("<!-- compare-link -->",
                        ' The three candidate looks are compared <a href="poppelsdorf/">in Poppelsdorf</a>.')
    (site / "index.html").write_text(page)

    # The Poppelsdorf comparison page, linking back to the city.
    demo = out_root / "poppelsdorf" / "demo"
    for f in demo.glob("*.png"):
        shutil.copy2(f, site / "poppelsdorf" / f.name)
    p = (demo / "index.html").read_text()
    p = p.replace("<!-- city-link -->", ' See <a href="../">all of Bonn</a>.')
    (site / "poppelsdorf" / "index.html").write_text(p)

    size = sum(f.stat().st_size for f in site.rglob("*") if f.is_file())
    if size > limit_mb * 1e6:
        raise ValueError(f"site is {size / 1e6:.0f} MB, over the {limit_mb:.0f} MB limit of GitHub Pages")
    archive = out_root / "site.tar.gz"
    with tarfile.open(archive, "w:gz", compresslevel=6) as tar:
        for f in sorted(site.rglob("*")):
            if f.is_file():
                tar.add(f, arcname=str(f.relative_to(site)))
    files = sum(1 for f in site.rglob("*") if f.is_file())
    print(f"site: {site} ({files} files, {size / 1e6:.0f} MB); archive {archive} ({archive.stat().st_size / 1e6:.0f} MB)")
    print(f"buildings {res['values']['buildings']}, tiles {res['values']['tiles']}")
    return archive
