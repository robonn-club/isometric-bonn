"""Map tiles and zoomed-out levels.

Tiles are 512 px squares of the global grid, named by their index from Bonn's corner
(projection.tile_index). A zoomed-out level halves the size by taking, in each 2 x 2 block,
the colour that occurs most often (the top-left one on a tie), so it stays on the palette.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .projection import TILE, Camera, tile_index


def halve(img: np.ndarray) -> np.ndarray:
    """Most-common-colour 2x downsampling of an (H, W, 3 or 4) uint8 image.

    Transparent pixels (alpha 0) count as one colour, so a block that is mostly outside the
    map stays outside, and a mostly-inside block keeps an on-palette colour.
    """
    h, w = img.shape[0] // 2 * 2, img.shape[1] // 2 * 2
    c = img.shape[2]
    px = img[:h, :w].astype(np.uint64)
    key = np.zeros(px.shape[:2], dtype=np.uint64)
    for i in range(c):
        key = (key << np.uint64(8)) | px[..., i]
    blocks = np.stack([key[0::2, 0::2], key[0::2, 1::2], key[1::2, 0::2], key[1::2, 1::2]], -1)
    counts = (blocks[..., :, None] == blocks[..., None, :]).sum(-1)
    pick = np.take_along_axis(blocks, counts.argmax(-1)[..., None], -1)[..., 0]
    out = [(pick >> np.uint64(8 * (c - 1 - i))) & np.uint64(255) for i in range(c)]
    return np.stack(out, -1).astype(np.uint8)


def save_png(img: np.ndarray, path: Path) -> None:
    """Save as an indexed PNG when there are at most 256 colours (exact, much smaller)."""
    flat = img.reshape(-1, 3)
    colours, index = np.unique(flat, axis=0, return_inverse=True)
    if len(colours) > 256:
        Image.fromarray(img).save(path, optimize=True)
        return
    p = Image.fromarray(index.reshape(img.shape[:2]).astype(np.uint8), mode="P")
    p.putpalette(colours.astype(np.uint8).ravel().tolist())
    p.save(path, optimize=True)


def write_tiles(img: np.ndarray, cam: Camera, origin: tuple[int, int], out: Path, fmt: str = "webp") -> list[Path]:
    """Cut a window image (origin on the tile grid) into 512 px tiles: <out>/<tx>_<ty>.<fmt>."""
    ox, oy = origin
    if ox % TILE or oy % TILE:
        raise ValueError("window origin is not on the tile grid")
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for j in range(img.shape[0] // TILE):
        for i in range(img.shape[1] // TILE):
            tx, ty = tile_index(cam, ox + i * TILE, oy + j * TILE)
            tile = Image.fromarray(img[j * TILE:(j + 1) * TILE, i * TILE:(i + 1) * TILE])
            path = out / f"{tx}_{ty}.{fmt}"
            if fmt == "webp":
                tile.save(path, lossless=True, method=6)
            else:
                tile.save(path, optimize=True)
            paths.append(path)
    return paths


def save_tile(tile: np.ndarray, path: Path) -> bool:
    """Lossless WebP; a fully transparent RGBA tile is not written. Returns whether it was."""
    if tile.shape[2] == 4 and not tile[..., 3].any():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(tile).save(path, lossless=True, method=6)
    return True


def tile_names(level_dir: Path) -> set[tuple[int, int]]:
    out = set()
    for f in level_dir.glob("*.webp"):
        x, y = f.stem.split("_")
        out.add((int(x), int(y)))
    return out


def build_pyramid(root: Path, log=print) -> int:
    """Zoomed-out levels root/1, root/2, ... from root/0, until one tile holds everything."""
    level = 0
    while True:
        names = tile_names(root / str(level))
        if len(names) <= 1 or not names:
            return level
        parents = {(x >> 1, y >> 1) for x, y in names}
        for px, py in sorted(parents):
            canvas = np.zeros((2 * TILE, 2 * TILE, 4), dtype=np.uint8)
            for dy in (0, 1):
                for dx in (0, 1):
                    child = (2 * px + dx, 2 * py + dy)
                    if child in names:
                        im = np.asarray(Image.open(root / str(level) / f"{child[0]}_{child[1]}.webp").convert("RGBA"))
                        canvas[dy * TILE:(dy + 1) * TILE, dx * TILE:(dx + 1) * TILE] = im
            save_tile(halve(canvas), root / str(level + 1) / f"{px}_{py}.webp")
        log(f"level {level + 1}: {len(parents)} tiles")
        level += 1


def pack(root: Path, out: Path, per_side: int = 4) -> dict[int, list[tuple[int, int]]]:
    """Sheets of per_side x per_side tiles for every level (fewer, larger files for a preview)."""
    levels = {}
    for d in sorted((p for p in root.iterdir() if p.name.isdigit()), key=lambda p: int(p.name)):
        lv = int(d.name)
        names = tile_names(d)
        sheets = {(x // per_side, y // per_side) for x, y in names}
        size = TILE * per_side
        for sx, sy in sorted(sheets):
            canvas = np.zeros((size, size, 4), dtype=np.uint8)
            for x, y in names:
                if x // per_side == sx and y // per_side == sy:
                    im = np.asarray(Image.open(d / f"{x}_{y}.webp").convert("RGBA"))
                    ox, oy = (x - sx * per_side) * TILE, (y - sy * per_side) * TILE
                    canvas[oy:oy + TILE, ox:ox + TILE] = im
            save_tile(canvas, out / str(lv) / f"{sx}_{sy}.webp")
        levels[lv] = sorted(sheets)
    return levels
