# Building plan: isometric map of Bonn

Status: approved 2026-11-07. On 2026-11-11 the scope was cut to Bonn only; the NRW stages are
dropped (their sizing is in this file's history, `daba8c0`). A Phase 0a prototype of Poppelsdorf
exists since 2026-11-11 (see [Prototype](#prototype-2026-11-11)). Sizes marked "measured" come from
the NRW download indexes on 2026-11-07. Times and the final look are estimates until Phases 0 and 1
test them.

## Context

Robonn wants a zoomable isometric pixel-art map of Bonn in the spirit of
[Isometric NYC](https://isometric.nyc). It serves the Year 1 goal of making the club visible, gives
members something they can add to by hand, and puts the city's robotics sites on a map people want
to explore.

Decisions Kaya made on 2026-11-07:

- **Reference:** Isometric NYC.
- **Name:** folder `projects/isometric-bonn`, public repo `robonn-club/isometric-bonn`.
- **Budget:** €0. No paid GPU and no paid hosting. AI restyling happens only if free GPU access
  comes through; otherwise a rule-based pixel style ships, rendered on the club laptop.
- **Form:** a standalone site, linked from robonn.de and the Industry Map like the other projects.
  Isometric coordinates don't fit the Industry Map's geographic basemap.
- **Scope (2026-11-11):** Bonn only. No NRW overview and no other cities.

## Approach

Isometric NYC rendered Google's 3D tiles, then restyled them with a fine-tuned image model. Two
parts of that don't carry over: Google's terms restrict caching, offline use and derived works,
and the model needs GPU time we won't pay for. So this plan builds the picture from NRW's open
data and turns it into pixel art with fixed rules, on the club laptop:

- **Shape:** LoD2 models for crisp buildings, a bare-ground model for terrain, and a
  height-above-ground model for everything else, including trees and bridges.
- **Colour:** each material (plants, paving, roofs, walls, water) gets a short ramp of palette
  shades. This is what should stop it reading as a posterised photo.
- **Small detail:** the brightness of the state's aerial photo picks the step on that ramp, so
  gardens, courtyards and road markings are real.
- **Charm and community:** landmarks and robots drawn by members as sprites.
- **AI:** a later upgrade, only if a free GPU turns up.

|                             | Isometric NYC                    | Isometric Bonn                                                                                    |
| --------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------- |
| 3D source                   | Google Photorealistic 3D Tiles   | NRW open data, licence `dl-de/zero-2-0` (no conditions)                                         |
| Pixel style                 | Image model on a rented H100     | Fixed rules on the laptop's RTX 4050; AI optional                                                 |
| Seams between tiles         | Placement rules and manual fixes | None by construction: every pixel is computed from world coordinates                              |
| Water and trees             | The hardest cases, fixed by hand | Water from polygons, trees shaped by measured heights                                             |
| Accuracy                    | The model can invent things      | Every building is real, with standardised roof shapes; only windows and wall colours are invented |
| Re-render                   | Paid, and results change         | Free and repeatable                                                                               |
| **Where it's weaker** | Rich, hand-painted detail        | **A more systematic look. Phase 0 tests whether it's good enough.**                         |

Expect the same family as Isometric NYC (isometric, pixel art, zoomable from city to single
building), but closer to a clean miniature city than to its painted richness.

**Related work:** the Industry Map has a Pixel view (`pixel.html`, its BACKLOG item 8, not yet
committed on 2026-11-07) that draws its entries as generated buildings on a model of Germany, on the
same 2:1 grid. It shows who is where, with positions shifted so every entry gets its own lot. This map
shows what places really look like. This plan assumes the two sit side by side and look related. Its
`js/pixel-sprites.js` also generates buildings, trees, cars and robot arms, which could supply pins and
robot scenes here.

## Data

All from [opengeodata.nrw.de](https://www.opengeodata.nrw.de/produkte/geobasis/), in EPSG:25832,
so nothing needs reprojecting. Tile layers come as 1 km squares, such as
`LoD2_32_365_5622_1_NW.gml`.

| Layer           | What it gives us                                                                 | Bonn, 14 × 16 km box (measured) | Licence                                     |
| --------------- | -------------------------------------------------------------------------------- | -------------------------------- | ------------------------------------------- |
| LoD2 CityGML    | Buildings with roof shapes; roofs and walls are separate surfaces                | 3.57 GB                          | zero                                        |
| DGM1 GeoTIFF    | Bare-ground height, 1 m grid                                                     | 0.48 GB                          | zero family; to confirm (see `SOURCES.md`) |
| nDOM50 GeoTIFF  | Height above ground, 50 cm grid: trees, bridges, anything LoD2 lacks             | 3.59 GB                          | zero; to confirm                            |
| DOP10 JP2       | Aerial photo, 10 cm, with an infrared band: brightness, and plants versus paving | 5.61 GB                          | zero; to confirm                            |
| Basis-DLM Shape | Water polygons                                                                   | 4.69 GB, one statewide file      | zero                                        |
| DVG1 Shape      | City boundary                                                                    | 0.02 GB, one statewide file      | zero                                        |

Bonn needs about 18 GB, which fits the 88 GB free on the laptop. Bonn's sources line up well: all
224 DOP10 tiles and 196 of 224 nDOM50 tiles are from 2025, and the three photo tiles checked were
flown on 2025-05-01, when trees should be in leaf (the four Poppelsdorf tiles too, per
`dop_meta.zip`).

Deliberately left out of the main pipeline:

- **OSM:** not needed for the picture, which avoids ODbL duties.
- **Bonn tree register:** CC0 with over 60,000 trees, but its endpoint returned 504 on 2026-11-07.
  Optional enrichment, not a dependency.
- **3D-Mesh NW:** a textured model of all NRW at 10 cm under the same licence, and the closest open
  match to Google's tiles. It's 11.4 TB (Bonn is one 182 GB block), and it stores one height per
  ground point, so walls are stretched. It's kept for the AI upgrade, which downloads that one block
  on whichever machine runs it, because the streaming service disallows robots (see below).

**Automated access.** Every script reads a host's robots.txt first and obeys it, whatever User-Agent
it sends. As read on 2026-11-07:

| Host                                | robots.txt                      | Use in this plan                                       |
| ----------------------------------- | ------------------------------- | ------------------------------------------------------ |
| `www.opengeodata.nrw.de`          | Empty, so nothing is disallowed | All bulk downloads                                     |
| `www.wms.nrw.de`                  | None                            | Not used (it was for the NRW overview)                 |
| `www.gis.nrw.de` (3D-Mesh stream) | Disallows everything            | Not used, unless Geobasis NRW agrees                   |
| `ckan.open.nrw.de`                | Disallows `/api/`             | Dataset pages only, read by a person                   |

## Scale

Detail is measured in pixels per metre along the view's 2:1 axes. A tile is 512 × 512 px, so
tiles = area in m² × (px/m)² ÷ 262,144. Lower zoom levels add about a third more files.

| px/m    | 10 m house is   | Bonn city, 141 km² | Note                                                                                  |
| ------- | --------------- | ------------------ | ------------------------------------------------------------------------------------- |
| 2.8     | ~57 px wide     | ~4,300 tiles       | Isometric NYC's level (~32,000 tiles in total); likely more than these rules can fill |
| **2**   | **~40 px wide** | **~2,150 tiles**   | **Default**                                                                           |
| 1.4     | ~28 px wide     | ~1,050 tiles       | Compared in Phase 0: chunkier pixels may read better                                  |
| 0.5     | ~10 px wide     | ~135 tiles         | Fallback if free hosting runs short                                                   |

All of Bonn uses one scale and one pixel grid; zoomed-out levels halve it.

## Pipeline

```
fetch > normalise > render data layers > stylise > add sprites > zoom levels > viewer > publish
```

1. **Fetch.** Save a frozen snapshot of each product's `index.json` (file, size, timestamp), so runs
   can be traced. Downloads check robots.txt first, resume, and use at most two connections.
2. **Normalise, per km².**
   - CityGML to triangles with surface type, building ID, function and height. `ClosureSurface` and
     the `bldg:address` fields are dropped, so no addresses enter the repo.
   - DGM1 to a terrain mesh.
   - nDOM50 to a height mesh, with LoD2 footprints and open water cut out. Bridges stay.
   - DOP10 to brightness, and to plants or paving using the infrared band.
   - Basis-DLM water polygons to a mask.
   - Vertices are baked into global screen coordinates in 64-bit and snapped to 1/16 px. 32-bit floats
     can't hold UTM coordinates to better than 0.5 m, and snapping keeps a vertex's pixels identical
     whichever tile it lands in. One permanent height reference applies everywhere.
3. **Render data layers.** Python with `moderngl` on the RTX 4050, without a display (headless EGL; the
   NVIDIA driver part is installed, untested). Orthographic view in one fixed global pixel grid. Each
   pixel records material, photo brightness, normal, depth, building ID, position on the wall and sun
   shadow. Tall buildings, hills and shadows shift things by up to about a tile, so source squares are
   chosen by projected bounds. Each tile renders 2 extra pixels per side for outlines. These layers are
   cached as files.
4. **Stylise, in plain NumPy on the cached layers.** Members can change the look from a small sample
   pack, without a GPU or the 18 GB of data. The rules:
   - Material ramps, with photo brightness choosing the step on ground and low roofs.
   - Roofs take one of 5–6 colour families per building, from a high percentile of the photo's colours.
   - Hard shadows and sun and shade sides on walls, with the sun matching the photo's midday light.
   - One-pixel outlines where building ID or depth changes.
   - Flat water.
   - Wall colours and windows by `bldg:function`, so sheds and garages get none. Window rows come from
     wall height, because LoD2 has no storey count.
   - No dithering at first: it compresses badly and reads as noise.
5. **Add sprites.** Landmarks and robots placed by world coordinates, depth-tested against the render.
6. **Zoom levels.** A small script builds lower levels with a most-common-colour filter, so they stay on
   the palette, and rebuilds only tiles whose hash changed. Tiles are lossless WebP.
7. **Viewer.** Static page with no build step on Leaflet with `CRS.Simple`, the club's existing map
   library, vendored here. Whole-step zoom and `image-rendering: pixelated` keep every pixel even. The
   cost is stepped zoom rather than Isometric NYC's smooth zoom; OpenSeadragon is the fallback if it feels
   wrong. Bonn is one tile layer.
   Deep links, self-hosted Outfit and Manrope, no API keys, no analytics, no third-party requests.
8. **Publish.** Tiles never enter git. They go into a GitHub Release as one archive, and a manually started
   workflow unpacks them beside the viewer and deploys to GitHub Pages, using the same deploy actions as
   `prototype-space/.github/workflows/pages.yml`. This keeps the repo small and needs no force pushes.

**Camera:** fixed at 30° elevation for exact 2:1 lines, looking north-east from the south-west. From the
bridge positions, the Rhine then runs within about 10° of level across the frame, with the Altstadt and
university in front of it and Beuel behind. Revisit the angle only if streets vanish in the Altstadt.

**One rule for every contribution:** fixes go in as rule changes or placed sprites, never as edits to
rendered tiles, so a re-render keeps them.

**Reuse from [isometric-nyc](https://github.com/cannoneyed/isometric-nyc) (MIT):** the rule-based pipeline
doesn't need its code. The AI upgrade can adapt its seam rules, infill templates and inference server,
keeping its notice. Its author warns the code is largely unreviewed, so we adapt pieces and don't fork. Its
model weights, training data and tiles are not reused.

**Original look:** the palette and sprites are our own, starting from the Rhein palette in
`website/src/css/style.css:19-29`. No game art or Isometric NYC tiles as material to copy. Phase 0a
checks it against the Pixel view's colours, so the two read as related.

## Who does what

- **Kaya:** creates the repo, runs all commits and pushes, sends requests to outside bodies, makes the go or
  no-go calls.
- **Ludwig (Claude Code):** pipeline code and docs, drafts of outside requests, commit messages and commands
  for Kaya.
- **Members:** sprites, review passes, the Phase 0 votes. One of them learns the deploy before launch, so it
  doesn't depend on one person.

## Phases

Week counts are estimates for one person at about 10 hours a week. W45's focus is backing up existing work,
so Phase 0 starts in W46 at the earliest. Steady work would put the Bonn launch around February 2027.

| Phase                                        | Work                                                                                                                                                                                                                                                                                                                                     | Done when                                                                                                                                                                                 | Estimate      |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------- |
| **0a. First picture**                  | Poppelsdorf, 1 km²: buildings and terrain in three looks side by side: flat material colours, photo brightness on material ramps, and a plain posterised photo as the comparison. No windows, water, trees, sprites or viewer. Kaya asks three members to draw one landmark each and asks the university's HPC team about free GPU use. | 3 of 5 members vote "game", not "GIS", for one look.                                                                                                                                      | 2–3 evenings |
| **0b. Hard sites**                     | Altstadt, Bundesviertel with Post Tower, Kennedybrücke and Beuel, Venusberg and Kottenforst, a suburb. Add the height mesh, shadows, water and windows. Compare 2 with 1.4 px/m. Encode sample tiles to check size.                                                                                                                     | Members recognise the forest, suburb, bridge and tower. The seam test passes. One member's sprite is merged.                                                                              | 1–2 weeks    |
| **1. One district live**               | About 10 km² from Altstadt to Poppelsdorf, end to end through publish. Test the deploy first with dummy files of Bonn's projected size.                                                                                                                                                                                                 | A credited public link works on phone and laptop. KB per tile and tiles per second are measured, with all Bonn projected under 1 GB. Kaya can deploy in 15 minutes.                       | 2 weeks       |
| **2. All Bonn**                        | City polygon from DVG1 with its edge drawn as a clear border, plus fixes from Phase 1.                                                                                                                                                                                                                                                   | Every km² reviewed by a member, with open bugs filed as issues with deep links. A rebuild from saved inputs matches tile hashes. The full deploy finishes inside Pages' 10-minute limit. | 2–3 weeks    |
| **3. Landmarks, pins, robots, launch** | About 10 landmark sprites, Industry Map pins, robot scenes, a sprite-drawing evening.                                                                                                                                                                                                                                                    | Linked from robonn.de, with landmarks from at least 3 contributors.                                                                                                                       | 3 weeks       |

If Phase 0 fails after one more style round, Kaya chooses between three options: try the AI upgrade if a free
GPU exists, hand-pixel a smaller hero area, or stop. The loss at that point is about two weeks of volunteer
time and no money.

### Phase 3 details

- **Landmarks, first round:** Münster, Altes Rathaus, Kurfürstliches Schloss, Poppelsdorfer Schloss, Post Tower,
  Langer Eugen, Kreuzbergkirche, Godesburg, and the three Rhine bridges.
- **Pins:** from the Industry Map's pushed data, loaded the way `scripts/validate.mjs:46-53` does, with sector
  colours from `js/common.js:20-35`. Bonn has 6 entries. Three Uni Bonn labs share one coordinate, so pins need
  spreading.
- **Mission fit:** robot sprites answer the review note in `references-examples.md:89` that Isometric NYC has no
  people, and they use the Wimmelbild idea at lines 94-98. Visitors can find field robots, inspection drones and
  warehouse robots at real sites. The Industry Map has an agriculture sector but none for energy or logistics, so
  those sites come from a small hand-picked `places.yaml`.
- **Contributing:** a member adds a PNG and one entry in `sprites.yaml` by pull request, following a short style
  guide. No tooling beyond git and a pixel editor; a palette check runs on the pull request. No company logos in
  sprites.
- **Accessibility:** a plain HTML list of places sits beside the map for keyboard and screen-reader users.
- **Launch edits:** the project lists in `website/src/index.njk:123-153`, the shared footer and the other pages
  that repeat those links.

## Prototype, 2026-11-11

A first Phase 0a run on 0.52 km² of Poppelsdorf (the Schloss, the botanic garden, the Allee and part of
Campus Poppelsdorf), end to end from download to tiles and a comparison page. Code in `src/isometric_bonn/`,
the area in `areas/poppelsdorf.yaml`, the rules in `style/`. What it showed:

- **Renderer.** A plain NumPy rasteriser stands in for `moderngl`: no GPU, driver or JIT, and the same
  bytes on any machine. The window renders in about 40 s on the laptop's CPU, so all of Bonn (about 270
  such windows) would take about 3 hours. The GPU path is needed only if that becomes too slow.
- **Seams.** The seam test passes on real data: the Schloss tile rendered on its own equals the same tile
  cut from the full window, byte for byte (`tests/test_seams_real_data.py`).
- **Parts of 0b came early,** because the picture needed them: hard shadows, windows by function, tree
  crowns from nDOM50 kept only where the infrared says plants (crowns float above the ground, so they don't
  melt into curtains), and water from the photo's infrared as a stand-in for Basis-DLM. The stand-in misses
  the green lily pond and needs the shadow test to skip dark streets.
- **Sun.** Estimated from the photo's own building shadows (`isobonn sun`): azimuth 152.5°, elevation 50°.
  That is Bonn's sun at about 12:15 CEST on 2025-05-01, the flight date `dop_meta.zip` gives for these tiles.
- **Roof lean.** `dop_meta.zip` says the photos are rectified on the image-based surface model (`bDOM`), so
  roofs should sit on their footprints. The 12 m limit for roof photo detail stays until the Bundesviertel test.
- **Roofs.** 804 of 923 roofs here are neutral grey, so a grey roof takes its shade from its own brightness;
  red, brown, green, copper and glass families cover the rest. Roof colours are measured in world space, so a
  building looks the same in every tile.
- **Size.** Tiles average 47 KB as lossless WebP, so all of Bonn with zoom levels comes to about 133 MB. That is
  dense streets; forest is still to measure.
- **Licences.** The products' metadata files carry no licence field, so DGM1, nDOM50 and DOP10 stay "to
  confirm" in `SOURCES.md`.
- **Still open for 0a:** the members' vote on the three looks (`isobonn demo poppelsdorf` builds the page), the
  1.4 px/m comparison, and Kaya's requests to three members and to the HPC team.

**All of Bonn, the same day** (Kaya: "Cover Bonn"). `isobonn city bonn` rendered the whole DVG1 city polygon, ahead
of Phases 1 and 2 and before the 0a vote, in the plan-default look:

- 141 km², 131,746 LoD2 buildings, 338 windows of 2048 × 1024 px, 1.65 CPU hours (about 50 minutes on two
  workers). Data: 989 files, 14.6 GB.
- 2,293 tiles at full size (113 MB, 49 KB each) and 169 MB with all eight zoom levels, so GitHub Pages' 1 GB holds
  it with room to spare.
- Each window renders with 4 px of overlap that is cropped, and ground, trees and buildings outside the boundary
  are left out, so the city is one piece of land with a dark edge line. A second seam test on real data checks
  two overlapping windows at the centre.
- Bridges: LoD2 has none, so raised structures from nDOM50 (over 4 m, not plants, wider than a bus) become
  floating decks; the Kennedybrücke and the station's platform roofs come out right, and ships turn into small
  decks. The Rhine is found by its infrared, which works well.
- Publishing is ready as step 8 describes: `isobonn site bonn` packs the site (about 175 MB), Kaya attaches it to a
  Release, and the manual workflow `.github/workflows/pages.yml` deploys it with the same actions as prototype-space.
  Tested locally under a sub-path: no requests to other hosts.
- Not yet reviewed by members (Phase 2's "every km² reviewed"), not yet deployed, and the look is still the 0a
  candidate.

## Optional AI upgrade

Starts only when a free GPU is confirmed, ideally with at least 24 GB (one LoRA trainer lists that for the base Qwen
Image model with quantisation; community guides claim less, so test it). Nothing else in the plan waits for it.

- **Free sources to try, in order:** Uni Bonn's Bender cluster (open to all university members, for teaching and small
  projects), Marvin (students may apply, for scientific projects), any cloud credit left from the October hackathon
  (status unknown). Kaggle's roughly 30 hours a week on 16 GB cards (community-reported, not official) probably suits
  inference tests only. Kaya asks in Phase 0a, because approval can take time, and describes it plainly as a club project.
  A "no" costs nothing.
- **Work:** about 40 training pairs, with targets painted by members or from a free-tier image model whose terms allow it.
  Fine-tune Qwen-Image-Edit (Apache-2.0).
- **First use, landmark sprites:** generate drafts for members to clean up. This needs almost no review time.
- **Then tiles, as a test:** restyle one 1 km² area using Isometric NYC's seam rules, and compare it side by side with the
  rule-based version. It goes wider only where members prefer it and someone commits the review hours. Isometric NYC's
  author reports that review took far longer than planned.

## Risks

| Risk                                                                                 | Earliest signal                   | Response                                                                                                                         |
| ------------------------------------------------------------------------------------ | --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| It reads as a posterised GIS render, not pixel art                                   | 0a vote                           | Another of the three looks, one more style round, then the three options above                                                   |
| Nobody draws sprites                                                                 | 0a request to three members       | A smaller landmark set from the core team; generated sprites in the Pixel view's manner; AI drafts if a GPU comes                |
| Volunteer time runs out                                                              | Phase 1 slips past 4 weeks        | One live district is already a result; grow district by district                                                                 |
| Forests and suburbs look dull                                                        | 0b sites                          | More ramp steps; tree sprites                                                                                                    |
| The height mesh gives melted trees, or noise on streets and water                    | 0b Kottenforst and Kennedybrücke | Filtering; forests stay as mesh, open-ground trees become sprites at nDOM50 peaks, with infrared filtering out trucks and cranes |
| The bridge deck is wrong in the height mesh                                          | 0b Kennedybrücke                 | Hand-built deck using DGM1 and nDOM50 heights                                                                                    |
| DOP10 roofs lean away from their footprints, so roof detail picks up walls or ground | 0b Bundesviertel                  | Tall roofs take a flat colour family and no photo brightness                                                                     |
| Windows look messy on walls that don't follow the pixel grid                         | 0b sites                          | Simplify them, or drop them on those walls                                                                                       |
| Basis-DLM polygons are too coarse or don't line up                                   | 0b Kennedybrücke                 | Cadastre land use (`lk/akt/gru_vereinfacht_gpkg`, licence zero, parcels without owners)                                        |
| Headless rendering fails on the laptop's two GPUs                                    | First hour of 0a                  | Avoided for now: the prototype renders on the CPU in NumPy (see Prototype)                                                       |
| Bonn exceeds 1 GB on GitHub Pages                                                    | 0b sample, then Phase 1           | Lower px/m, or crop to the city polygon                                                                                          |
| The laptop is short on memory (about 3 GB free when checked)                         | 0a                                | Work one km² at a time; run while other jobs are stopped                                                                        |

## Repo layout

Follows the sibling projects' pattern.

```
projects/isometric-bonn/
  building-plan.md
  README.md  LICENSE  LICENSE-ART  CONTRIBUTING.md  references-examples.md  SOURCES.md
  pyproject.toml  uv.lock
  areas/*.yaml                          # test areas now; Bonn's boundary later
  style/style.yaml  style/palette.yaml  # camera, sun, colour rules and the palette
  src/isometric_bonn/                   # fetch, normalise, render, stylise, sprites, zoom levels
  sprites/  sprites.yaml  places.yaml
  viewer/
  tests/
  .github/workflows/                    # deploy from a Release; link check; palette check
  data/manifest.json                    # tracked; everything else in data/ and out/ is gitignored
```

- **Licences:** code MIT (like the Industry Map), tiles and sprites CC BY 4.0 (like the guidebook). The data needs no
  credit, but the footer credits Geobasis NRW and Isometric NYC anyway.
- **Registration, once the repo exists:** add it to `ludwig/conventions.md` (repo table and public-repos rule),
  `ludwig/WORKSPACE-MAP.md` and the root `CLAUDE.md`.
- **Legal:** the footer links to robonn.de's Impressum and privacy pages.

## Verification

- **Seams:** one 1024 × 1024 render must match its four 512 × 512 tiles byte for byte, at Post Tower and on Venusberg
  (automated test).
- **Repeatability:** a rebuild from saved inputs matches tile hashes on the same machine (automated test).
- **Position:** about 20 known landmarks land within a few pixels of their projected position.
- **No addresses:** a test confirms normalised data has no address fields.
- **Palette:** every tile and sprite uses only palette colours (automated test).
- **Licences:** each source's licence is recorded in `SOURCES.md`, with DGM1, nDOM50 and DOP10 confirmed there.
- **Viewer:** works at phone width and by keyboard; the browser's network panel shows no third-party requests; the first
  view loads under about 5 MB; site size is under 1 GB and the deploy finishes in time.
- **People:** the Phase 0 votes, then the same members try the live map on their phones before launch.

## Sources

- [Isometric NYC write-up](https://cannoneyed.com/projects/isometric-nyc) and
  [code](https://github.com/cannoneyed/isometric-nyc)
- [Google Map Tiles API policies](https://developers.google.com/maps/documentation/tile/policies)
- [OpenGeodata.NRW](https://www.opengeodata.nrw.de/produkte/geobasis/),
  [LoD2 API](https://ogc-api.nrw.de/3dg/v1),
  [3D-Mesh NW](https://ckan.open.nrw.de/dataset/5f59c9b2-ad96-4775-afcb-3964f6f4a2dc),
  [simplified cadastre](https://ckan.open.nrw.de/sl/dataset/3e8cf42f-7faa-4bee-b71a-fc6c01d26213),
  [licence dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0)
- [Bonn tree register](https://opendata.bonn.de/dataset/baumstandorte)
- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits)
- [Uni Bonn HPC systems](https://www.hpc.uni-bonn.de/en/systems/marvin),
  [Qwen-Image-Edit](https://huggingface.co/Qwen/Qwen-Image-Edit)
