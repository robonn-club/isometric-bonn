"""Stylise: turn rendered data layers into pixel art, in plain NumPy.

Works from out/<area>/layers.npz alone, so the look can be changed without the raw data
or a GPU. Every pixel is chosen as (ramp, step) from style/palette.yaml and only turned
into a colour at the end, so the output holds palette colours and nothing else.

Looks, for the Phase 0a comparison:
  flat   each material one colour, lit by the sun
  ramp   the aerial photo's brightness picks the step on each material's ramp (plan default)
  photo  the aerial photo draped on the model and posterised, the "GIS" baseline

Every rule reads a pixel and its direct neighbours only, so a tile styled on its own
matches the same area styled as part of a larger window (given a 2 px margin).
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np
from PIL import Image
from scipy import ndimage

from .projection import sun_vector
from .scene import DECK, GROUND, ROOF, TREE, WALL, WATER

LOOKS = ("flat", "ramp", "photo")


@dataclass
class Palette:
    names: list[str]
    lengths: np.ndarray
    offsets: np.ndarray
    rgb: np.ndarray  # (k, 3) uint8

    @classmethod
    def from_ramps(cls, ramps: dict[str, list[str]]) -> "Palette":
        names = list(ramps)
        lengths = np.array([len(ramps[n]) for n in names])
        offsets = np.r_[0, np.cumsum(lengths)[:-1]]
        rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for n in names for c in ramps[n]],
                       dtype=np.uint8)
        return cls(names, lengths, offsets, rgb)

    def rid(self, name: str) -> int:
        return self.names.index(name)

    def index(self, ramp, step):
        ramp = np.asarray(ramp)
        step = np.clip(np.asarray(step), 0, self.lengths[ramp] - 1)
        return self.offsets[ramp] + step


# --- what each building is -------------------------------------------------------------------

WINDOWS = {  # storey height, sill, window height, spacing, window width (metres)
    "home": (3.0, 0.9, 1.3, 2.6, 1.1),
    "public": (3.8, 1.0, 1.9, 2.3, 1.4),
    "work": (3.6, 1.0, 1.6, 2.5, 1.6),
}


def wall_kind(function: str, height: float) -> tuple[str, str | None]:
    """Wall ramp and window pattern from the ALKIS building function code."""
    group, _, num = function.partition("_")
    n = int(num) if num.isdigit() else 0
    if group != "31001":  # roofs over walkways, carports, bridges and other structures
        return "wall_shed", None
    if n == 2740:  # greenhouse
        return "glass", None
    if 2460 <= n <= 2465:  # garages and car parks
        return "wall_shed", None
    if 1000 <= n < 2000:
        return "wall_plaster", "home"
    if 3000 <= n < 4000:
        return "wall_stone", "public"
    if 2000 <= n < 3000:
        return ("wall_concrete", "work") if height >= 7 else ("wall_shed", None)
    return "wall_plaster", "home"


def stable_pick(key: str, options: list[str]) -> str:
    """The same choice for a building in every tile and every run."""
    return options[zlib.crc32(key.encode()) % len(options)]


# --- the looks ---------------------------------------------------------------------------------

def _levels(x, lo, hi, n):
    return np.clip(np.floor((x - lo) / (hi - lo) * n), 0, n - 1).astype(np.int16)


def stylise(layers: dict, meta: dict, ramps: dict, cfg: dict, look: str = "ramp") -> np.ndarray:
    """Return an (H, W, 3) uint8 image of one look."""
    pal = Palette.from_ramps(ramps)
    mat = layers["mat"]
    bld = layers["bld"]
    photo = layers["photo"].astype(np.float32)
    shadow = layers["shadow"]
    normal = layers["normal"].astype(np.float64)
    sun = sun_vector(meta["sun"]["azimuth"], meta["sun"]["elevation"])
    lam = normal @ sun
    r, g, b, nir = (photo[..., i] for i in range(4))
    ndvi = (nir - r) / (nir + r + 1e-6)
    luma = 0.299 * r + 0.587 * g + 0.114 * b

    if look == "photo":
        return _photo_look(photo, lam, mat, cfg)

    h, w = mat.shape
    ramp = np.full((h, w), pal.rid("background"), dtype=np.int16)
    step = np.zeros((h, w), dtype=np.int16)
    use_photo = look == "ramp"
    gcfg = cfg["ground"]

    # Ground: grass, bare soil or paving, by infrared and colour.
    gnd = mat == GROUND
    k = int(gcfg.get("smooth", 1))
    gl = ndimage.median_filter(luma, size=k) if k > 1 else luma
    warm = (r - b > gcfg["soil_warmth"]) & (luma > gcfg["soil_min_luma"])
    is_grass = gnd & (ndvi > gcfg["grass_ndvi"])
    is_soil = gnd & ~is_grass & warm & (ndvi > gcfg["soil_min_ndvi"])
    is_pave = gnd & ~is_grass & ~is_soil
    for mask, name, (lo, hi), flat in (
        (is_grass, "grass", gcfg["grass_luma"], 4),
        (is_soil, "soil", gcfg["soil_luma"], 3),
        (is_pave, "paving", gcfg["paving_luma"], 6),
    ):
        n = pal.lengths[pal.rid(name)]
        ramp[mask] = pal.rid(name)
        step[mask] = _levels(gl[mask], lo, hi, n) if use_photo else flat

    # Bridges and other decks: the photo's asphalt on top, concrete on the sides.
    dek = mat == DECK
    top = dek & (normal[..., 2] > 0.6)
    side = dek & ~top
    n_pave = pal.lengths[pal.rid("paving")]
    ramp[top] = pal.rid("paving")
    step[top] = _levels(gl[top], *gcfg["paving_luma"], n_pave) if use_photo else 6
    ramp[side] = pal.rid("wall_concrete")
    step[side] = np.where(lam[side] > cfg["wall"]["lit"], 2, 1)

    # Water: flat, one step lighter along the banks.
    wat = mat == WATER
    ramp[wat] = pal.rid("water")
    bank = wat & ~ndimage.binary_erosion(wat, border_value=1)
    step[wat] = 2
    step[bank] = 3

    # Trees: sun on the rounded crown; on crown tops, also the photo's light and dark crowns.
    # Steep crown sides take the sun only: there every pixel down a column would repeat the
    # same photo sample, which paints vertical streaks.
    tre = mat == TREE
    n_tree = pal.lengths[pal.rid("tree")]
    light = np.clip((lam[tre] - 0.2) / 0.75, 0, 1)
    if use_photo:
        lo, hi = cfg["tree"]["luma"]
        wp = 0.45 * np.clip(normal[..., 2][tre], 0, 1) ** 2
        lvl = (1 - wp) * light + wp * np.clip((luma[tre] - lo) / (hi - lo), 0, 1)
    else:
        lvl = 0.25 + 0.6 * light
    ramp[tre] = pal.rid("tree")
    step[tre] = np.clip(np.floor(lvl * n_tree), 0, n_tree - 1)

    # Roofs: a family and a base step per building from the photo, then the sun per slope.
    nb = len(layers["bld_function"])
    roofs = (mat == ROOF) & (bld >= 0)
    rcfg = cfg["roof"]
    fam, base = _roof_families(layers, pal, rcfg)
    fam = np.append(fam, pal.rid("roof_grey")).astype(np.int16)
    base = np.append(base, 3).astype(np.int16)
    bi = bld[roofs]
    ramp[roofs] = fam[bi]
    rstep = base[bi] + _levels(lam[roofs], rcfg["sun_lo"], rcfg["sun_hi"], 4) - 2
    if use_photo:
        # Low roofs show the photo's detail (skylights, solar panels, terraces); tall roofs
        # lean in the photo, so they keep plain steps.
        diff = luma[roofs] - layers["bld_roof_luma"][bi]
        low = layers["bld_height"][bi] < rcfg["photo_max_height"]
        rstep += np.where(low, np.clip(np.round(diff / rcfg["photo_step_luma"]), -1, 1), 0).astype(np.int16)
    step[roofs] = rstep

    # Walls: material by building function (homes in one of a few tints), sun and shade side.
    walls = (mat == WALL) & (bld >= 0)
    kinds = [wall_kind(f, float(hh)) for f, hh in zip(layers["bld_function"], layers["bld_height"])]
    tints = cfg["wall"].get("home_tints", ["wall_plaster"])
    names = [stable_pick(gid, tints) if k == "wall_plaster" else k
             for (k, _), gid in zip(kinds, layers["bld_gmlid"])]
    wall_ids = np.array([pal.rid(n) for n in names] + [pal.rid("wall_plaster")], dtype=np.int16)
    bw = np.where(walls, bld, nb)
    ramp[walls] = wall_ids[bw[walls]]
    lit = lam > cfg["wall"]["lit"]
    strong = lam > cfg["wall"]["strong"]
    wstep = np.where(lit, np.where(strong, 3, 2), 1)
    wstep = np.where(shadow, np.minimum(wstep, 2) - 1, wstep)
    is_glass = ramp == pal.rid("glass")
    step[walls] = wstep[walls] + np.where(is_glass[walls], 1, 0)

    # Windows, in rows by storey and columns along each wall.
    if cfg["wall"].get("windows", True):
        pattern = np.array([k[1] or "" for k in kinds] + [""])
        win = _windows(layers, walls, pattern[bw])
        ramp[win] = pal.rid("window")
        step[win] = (lit & ~shadow)[win].astype(np.int16)

    # Shadows: steps down on ground, roofs, trees and water.
    sh = shadow & (gnd | tre | roofs | top)
    step[sh] -= cfg["shadow_steps"]
    step[shadow & wat] -= 1
    step = np.maximum(step, 0)

    # One-pixel outlines on silhouettes, and between buildings.
    edge_obj, edge_tree = _outlines(layers, cfg)
    ramp[edge_obj] = pal.rid("outline")
    step[edge_obj] = 0
    ramp[edge_tree] = pal.rid("tree")
    step[edge_tree] = 0

    return pal.rgb[pal.index(ramp, step)]


def _roof_families(layers, pal, rcfg):
    """Each building's roof family and base step, from its sunlit roof in the photo.

    Most roofs here are neutral grey and the photo has a cool cast, so colours are judged
    after a fixed white balance (style.yaml, roof.white_rg). Grey roofs take their step on
    one grey ramp from their own brightness; warm roofs are tile (red or brown), cyan-green
    ones copper, planted ones green; greenhouses are glass. Statistics come from the render
    step in world space, so a building looks the same in every tile.
    """
    rgb = layers["bld_roof_rgb"].astype(np.float64)
    ml = layers["bld_roof_luma"].astype(np.float64)
    nd = layers["bld_roof_ndvi"].astype(np.float64)
    seen = layers["bld_roof_cells"] > 0
    rg = (rgb[:, 0] - rgb[:, 1]) - rcfg["white_rg"]
    nb = len(ml)
    fam = np.full(nb, pal.rid("roof_grey"))
    base = np.zeros(nb, dtype=np.int64)
    lo, hi = rcfg["luma"]
    for i in range(nb):
        f = layers["bld_function"][i]
        if f.startswith("31001_2740"):
            name = "glass"
        elif nd[i] > 0.2:
            name = "roof_green"
        elif rg[i] > rcfg["warm"]:
            name = "roof_red" if rg[i] > 2 * rcfg["warm"] and ml[i] > 70 else "roof_brown"
        elif rg[i] < rcfg["copper"] and rgb[i, 2] > rgb[i, 0]:
            name = "roof_copper"
        else:
            name = "roof_grey"
        fam[i] = pal.rid(name)
        n = int(pal.lengths[fam[i]])
        base[i] = _levels(np.array([ml[i]]), lo, hi, n)[0] if seen[i] else n // 2
    return fam, base


def _windows(layers, walls, pattern):
    u, hgt, length = layers["wall_u"], layers["wall_h"], layers["wall_len"]
    out = np.zeros(walls.shape, dtype=bool)
    for name, (storey, sill, wh, spacing, ww) in WINDOWS.items():
        m = walls & (pattern == name) & np.isfinite(u) & np.isfinite(hgt)
        if not m.any():
            continue
        uu, hh, ll = u[m], hgt[m], length[m]
        in_row = ((hh % storey) >= sill) & ((hh % storey) < sill + wh) & (hh > 0)
        ncol = np.floor((ll - 1.2) / spacing).astype(np.int64) + 1
        start = (ll - (ncol - 1) * spacing) / 2
        k = np.clip(np.round((uu - start) / spacing), 0, np.maximum(ncol - 1, 0))
        in_col = (np.abs(uu - (start + k * spacing)) < ww / 2) & (ncol >= 1) & (ll >= 2.5)
        out[m] = in_row & in_col
    return out


def _outlines(layers, cfg):
    """Silhouettes: an object pixel whose neighbour lies well behind it, or belongs to
    another building at about the same depth. Ground and water never get an outline."""
    mat, bld, d = layers["mat"], layers["bld"], layers["depth"].astype(np.float64)
    obj = (mat == ROOF) | (mat == WALL) | (mat == TREE) | (mat == DECK)
    tree = mat == TREE
    t = np.where(tree, cfg.get("outline_tree_depth_m", cfg["outline_depth_m"]), cfg["outline_depth_m"])
    edge = np.zeros(mat.shape, dtype=bool)
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nd = np.full(d.shape, np.inf)
        nb = np.full(bld.shape, -1)
        ys = slice(max(dy, 0), d.shape[0] + min(dy, 0))
        yd = slice(max(-dy, 0), d.shape[0] + min(-dy, 0))
        xs = slice(max(dx, 0), d.shape[1] + min(dx, 0))
        xd = slice(max(-dx, 0), d.shape[1] + min(-dx, 0))
        nd[yd, xd] = d[ys, xs]
        nb[yd, xd] = bld[ys, xs]
        with np.errstate(invalid="ignore"):  # empty pixels: inf - inf
            behind = nd - d > t
        other = (bld >= 0) & (nb >= 0) & (nb != bld) & (nd > d)
        edge |= obj & (behind | other)
    # Ground and water next to empty pixels (the city's edge) get the line as well.
    flat = (mat == GROUND) | (mat == WATER)
    empty = np.pad(mat == 0, 1, constant_values=False)
    next_to_empty = empty[:-2, 1:-1] | empty[2:, 1:-1] | empty[1:-1, :-2] | empty[1:-1, 2:]
    edge |= flat & next_to_empty
    return edge & ~tree, edge & tree


def _photo_look(photo, lam, mat, cfg):
    rgb = photo[..., :3].copy()
    walls = mat == WALL
    shade = np.where(lam > 0.1, 1.0, 0.7)
    rgb[walls] *= shade[walls][:, None]
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8))
    q = img.quantize(colors=int(cfg["photo_colours"]), method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    return np.asarray(q.convert("RGB"))
