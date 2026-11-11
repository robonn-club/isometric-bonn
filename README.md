# Isometric Bonn

A zoomable isometric pixel-art map of Bonn, built from the state's open 3D data by fixed rules
on one laptop. A project of [Robonn](https://robonn.de), the robotics club at Universität Bonn.

**Status (2026-11-11):** Phase 0a prototype. A test area, Poppelsdorf (0.52 km² around
Poppelsdorfer Schloss), goes end to end from download to map tiles and a comparison page with
three looks, and all of Bonn (141 km²) has been rendered once in the default look. The plan,
phases and decisions are in [`building-plan.md`](building-plan.md).

## Run it

Needs Python 3.12 and [uv](https://docs.astral.sh/uv/). No GPU.

```sh
uv sync                              # once, creates .venv (and uv.lock)
uv run isobonn all poppelsdorf       # fetch, render, style, demo
xdg-open out/poppelsdorf/demo/index.html
```

`all` runs four steps, which also work one by one:

| Command | What it does | Time |
| --- | --- | --- |
| `isobonn fetch poppelsdorf` | Downloads the four 1 km tiles of each product (16 files, 350 MB) into `data/raw/`, after reading the host's robots.txt. Records each file in `data/manifest.json`. | under a minute |
| `isobonn render poppelsdorf` | Renders the data layers into `out/poppelsdorf/layers.npz`: material, building, normal, depth, world position, photo colour, sun shadow and wall position for every pixel. | about 40 s |
| `isobonn style poppelsdorf` | Colours the layers: `flat.png`, `ramp.png`, `photo.png`, half-size versions, and 512 px tiles in `tiles/`. | seconds |
| `isobonn demo poppelsdorf` | Builds the comparison page in `out/poppelsdorf/demo/`. | seconds |

`isobonn sun poppelsdorf` estimates the aerial photo's sun from its building shadows; its result
is already in `style/style.yaml`.

### All of Bonn

```sh
uv run isobonn city bonn --workers 2 --drop-layers
xdg-open out/bonn/viewer/index.html
```

This takes Bonn's boundary from DVG1, downloads the 236 data tiles it needs (about 14 GB), and
renders 338 windows of 2048 × 1024 px, each with a 4 px overlap that is cropped so neighbours
match exactly. Ground, trees and buildings outside the boundary are left out; the boundary gets a
dark line. Then it builds the zoom levels and a viewer. Each worker needs about 3.5 GB of memory.
The run can stop at any time: `out/bonn/progress.json` records finished windows, and the same
command continues. Without `--drop-layers` each window also keeps its layers (about 50 MB each),
so the whole city can be recoloured without rendering again.

## Change the look

Colours are in [`style/palette.yaml`](style/palette.yaml), rules and thresholds in
[`style/style.yaml`](style/style.yaml). After an edit, `uv run isobonn style poppelsdorf`
recolours the area in seconds. It needs only `out/poppelsdorf/layers.npz`, not the raw data, so
that one file is enough to experiment with. Fixes go in as rule changes, never as edits to
rendered images, so a re-render keeps them.

## How it works

1. **Fetch.** LoD2 buildings, DGM1 ground heights, nDOM50 heights above ground and the DOP10
   aerial photo from [OpenGeodata.NRW](https://www.opengeodata.nrw.de/produkte/geobasis/).
2. **Model.** Roofs and walls from LoD2. Ground and tree crowns as 0.5 m height meshes; heights
   count as trees only where the photo's infrared says plants, and crowns float above the ground
   so they don't melt into curtains. Bridges and other raised structures LoD2 lacks become floating
   decks. Water comes from the infrared for now.
3. **Render.** One fixed pixel grid for all of Bonn at 2 px per metre, camera at 30° looking
   north-east, rasterised in plain NumPy with exact integer edge tests, so a tile is the same
   bytes on any machine and in any window. Hard shadows use the photo's own sun.
4. **Style.** Every pixel picks a step on a palette ramp: the photo's brightness on ground and
   low roofs, the sun on walls and roof slopes, each roof's family from the photo, walls and
   windows from the building's use. Outlines on silhouettes.
5. **Tiles.** 512 px lossless WebP, indexed from Bonn's corner; zoomed-out images keep the most
   common colour of each 2 × 2 block, so they stay on the palette.

## Layout

```
areas/          test areas (centre, size, labels)
style/          camera, sun, colour rules (style.yaml) and the palette (palette.yaml)
src/isometric_bonn/
  fetch.py      downloads with robots.txt, manifest       geo.py        lat/lon to EPSG:25832
  citygml.py    LoD2 to triangles, no addresses           rasters.py    DGM1, nDOM50, DOP10 grids
  projection.py camera and the global pixel grid          rasterize.py  the NumPy rasteriser
  scene.py      data layers, shadows, water               sun.py        sun from the photo's shadows
  style.py      the three looks                           tiles.py      tiles and zoom levels
  demo.py       the comparison page                       cli.py        `isobonn`
viewer/         page template and self-hosted fonts (SIL OFL)
tests/          rasteriser, camera, CityGML, palette, and the seam test on real data
data/           downloads (ignored); manifest.json is tracked
out/            renders (ignored)
```

## Tests

```sh
uv run pytest
```

The seam test (`tests/test_seams_real_data.py`) renders one tile on its own and compares it with
the same tile in the full window, byte for byte. It needs the Poppelsdorf data and render, and
skips without them.

## Data and licences

Sources, survey dates and licence status are in [`SOURCES.md`](SOURCES.md). Code is MIT
([`LICENSE`](LICENSE)). Map tiles and sprites will be CC BY 4.0 once they are published.
