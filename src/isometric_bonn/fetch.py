"""Fetch: download NRW open-data tiles politely and record exactly what was used.

Rules, from building-plan.md:
- read each host's robots.txt before the first request and obey it, whatever User-Agent
  we send; run from a Claude Code session, the rules for Claude's agents apply as well;
- one connection at a time, resumable downloads;
- a frozen snapshot of each product's index.json, and a tracked manifest
  (data/manifest.json) listing every file used with its size, timestamp and SHA-256.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from pathlib import Path

# A generic client name. Set ISOBONN_USER_AGENT to add a contact if you want one.
USER_AGENT = os.environ.get("ISOBONN_USER_AGENT", "isobonn-fetch/0.1 (python-urllib)")

# Agents whose robots.txt rules also apply when this runs inside a Claude Code session.
CLAUDE_AGENTS = ("Claude-User", "ClaudeBot", "Claude-Web", "anthropic-ai")

BASE = "https://www.opengeodata.nrw.de/produkte/geobasis/"


@dataclass(frozen=True)
class Product:
    key: str
    directory: str  # relative to BASE, ends with "/"
    stem: str  # file name start for one 1 km tile, with {e} and {n} in km
    licence: str
    note: str

    @property
    def url(self) -> str:
        return BASE + self.directory

    def tile_stem(self, e_km: int, n_km: int) -> str:
        return self.stem.format(e=e_km, n=n_km).lower()


PRODUCTS = {
    p.key: p
    for p in (
        Product("lod2", "3dg/lod2_gml/lod2_gml/", "LoD2_32_{e}_{n}_1_", "dl-de/zero-2-0",
                "Buildings with roof shapes (CityGML 1.0)"),
        Product("dgm1", "hm/dgm1_tiff/dgm1_tiff/", "dgm1_32_{e}_{n}_1_", "dl-de/zero-2-0 (confirm from metadata)",
                "Bare-ground height, 1 m grid"),
        Product("ndom50", "hm/ndom50_tiff/ndom50_tiff/", "ndom50_32{e}_{n}_1_", "dl-de/zero-2-0 (confirm from metadata)",
                "Height above ground, 0.5 m grid"),
        Product("dop10", "lusat/akt/dop/dop_jp2_f10/", "dop10rgbi_32_{e}_{n}_1_", "dl-de/zero-2-0 (confirm from metadata)",
                "Aerial photo, 10 cm, red/green/blue/infrared"),
    )
}


class RobotsDisallowed(RuntimeError):
    pass


_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


def _agents() -> tuple[str, ...]:
    return (USER_AGENT, "*") + (CLAUDE_AGENTS if os.environ.get("CLAUDECODE") else ())


def check_robots(url: str) -> None:
    """Raise RobotsDisallowed unless robots.txt allows `url` for every agent that applies."""
    parts = urllib.parse.urlsplit(url)
    root = f"{parts.scheme}://{parts.netloc}"
    rp = _robots.get(root)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser(root + "/robots.txt")
        req = urllib.request.Request(root + "/robots.txt", headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                rp.parse(r.read().decode("utf-8", "replace").splitlines())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                rp.disallow_all = True
            elif 400 <= e.code < 500:
                rp.allow_all = True
            else:
                raise
        _robots[root] = rp
    for agent in _agents():
        if not rp.can_fetch(agent, url):
            raise RobotsDisallowed(f"robots.txt of {root} disallows {url} for {agent}")


def _get(url: str, timeout: float = 60) -> bytes:
    check_robots(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_index(product: Product, data_dir: Path, max_age_days: float = 30) -> dict[str, dict]:
    """Return {file name: {size, timestamp}} from the product's index.json.

    The raw index is saved as data/index/<key>.json with the date it was read, and reused
    while it is younger than `max_age_days`, so repeated runs cost no requests.
    """
    path = data_dir / "index" / f"{product.key}.json"
    if path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400:
        raw = json.loads(path.read_text())
    else:
        raw = {"read": dt.date.today().isoformat(), "url": product.url + "index.json",
               "index": json.loads(_get(product.url + "index.json", timeout=120))}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(raw))
    files = {}
    for ds in raw["index"].get("datasets", []):
        for f in ds.get("files", []):
            files[f["name"]] = {"size": int(f.get("size", 0)), "timestamp": f.get("timestamp", "")}
    return files


def tile_file(product: Product, files: dict[str, dict], e_km: int, n_km: int) -> str:
    """Pick the file for one 1 km tile. Several survey years may exist; take the newest."""
    stem = product.tile_stem(e_km, n_km)
    hits = sorted(name for name in files if name.lower().startswith(stem))
    if not hits:
        raise FileNotFoundError(f"{product.key}: no file for tile {e_km}_{n_km}")
    return hits[-1]


def download(url: str, dest: Path, size: int | None = None) -> Path:
    """Download to `dest`, resuming a partial `.part` file. One connection, no parallelism."""
    if dest.exists() and (size is None or dest.stat().st_size == size):
        return dest
    check_robots(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": USER_AGENT}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as r:
        mode = "ab" if have and r.status == 206 else "wb"
        with open(part, mode) as out:
            shutil.copyfileobj(r, out, length=1 << 20)
    if size is not None and part.stat().st_size != size:
        raise IOError(f"{dest.name}: got {part.stat().st_size} bytes, index says {size}")
    part.rename(dest)
    return dest


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_tiles(tiles: list[tuple[int, int]], data_dir: Path, products=("lod2", "dgm1", "ndom50", "dop10"),
                log=print) -> dict:
    """Download every product for every tile and update data/manifest.json. Returns the manifest."""
    manifest_path = data_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"files": {}}
    for key in products:
        product = PRODUCTS[key]
        files = fetch_index(product, data_dir)
        for e_km, n_km in tiles:
            name = tile_file(product, files, e_km, n_km)
            info = files[name]
            dest = data_dir / "raw" / key / name
            if not (dest.exists() and dest.stat().st_size == info["size"]):
                log(f"  {key}: {name} ({info['size'] / 1e6:.1f} MB)")
            download(product.url + name, dest, info["size"])
            entry = manifest["files"].get(name)
            if not entry or entry.get("size") != info["size"]:
                entry = {"product": key, "url": product.url + name, "size": info["size"],
                         "timestamp": info["timestamp"], "licence": product.licence,
                         "sha256": sha256(dest), "fetched": dt.date.today().isoformat()}
                manifest["files"][name] = entry
    manifest["files"] = dict(sorted(manifest["files"].items()))
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def local_file(data_dir: Path, key: str, e_km: int, n_km: int) -> Path:
    """The downloaded file for one product and tile, found through the manifest."""
    manifest = json.loads((data_dir / "manifest.json").read_text())
    stem = PRODUCTS[key].tile_stem(e_km, n_km)
    names = sorted(n for n, f in manifest["files"].items() if f["product"] == key and n.lower().startswith(stem))
    if not names:
        raise FileNotFoundError(f"{key} {e_km}_{n_km} not fetched yet: run `isobonn fetch`")
    return data_dir / "raw" / key / names[-1]
