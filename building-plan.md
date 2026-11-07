# Building plan: isometric map of Bonn, then NRW

Status: approved 2026-11-07. Nothing is built yet. Sizes marked "measured" come from the NRW
download indexes on 2026-11-07. Times, tile sizes and the final look are estimates until Phases 0
and 1 test them.

## Context

Robonn wants a zoomable isometric pixel-art map in the spirit of
[Isometric NYC](https://isometric.nyc), first of Bonn and then of all NRW. It serves the Year 1
goal of making the club visible, gives members something they can add to by hand, and puts the
region's robotics sites on a map people want to explore.

Decisions Kaya made on 2026-11-07:

- **Reference:** Isometric NYC.
- **Name:** folder `projects/isometric-bonn`, public repo `robonn-club/isometric-bonn`.
- **Budget:** €0. No paid GPU and no paid hosting. AI restyling happens only if free GPU access
  comes through; otherwise a rule-based pixel style ships, rendered on the club laptop.
- **Form:** a standalone site, linked from robonn.de and the Industry Map like the other projects.
  Isometric coordinates don't fit the Industry Map's geographic basemap.

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

| | Isometric NYC | Isometric Bonn |
|---|---|---|
| 3D source | Google Photorealistic 3D Tiles | NRW open data, licence `dl-de/zero-2-0` (no conditions) |
| Pixel style | Image model on a rented H100 | Fixed rules on the laptop's RTX 4050; AI optional |
| Seams between tiles | Placement rules and manual fixes | None by construction: every pixel is computed from world coordinates |
| Water and trees | The hardest cases, fixed by hand | Water from polygons, trees shaped by measured heights |
| Accuracy | The model can invent things | Every building is real, with standardised roof shapes; only windows and wall colours are invented |
| Re-render | Paid, and results change | Free and repeatable |
| **Where it's weaker** | Rich, hand-painted detail | **A more systematic look. Phase 0 tests whether it's good enough.** |

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

| Layer | What it gives us | Bonn, 14 × 16 km box (measured) | All NRW (measured) | Licence |
|---|---|---|---|---|
| LoD2 CityGML | Buildings with roof shapes; roofs and walls are separate surfaces | 3.57 GB | 219.6 GB | zero |
| DGM1 GeoTIFF | Bare-ground height, 1 m grid | 0.48 GB | 78.8 GB | zero family; confirm from `dgm1_meta.zip` |
| nDOM50 GeoTIFF | Height above ground, 50 cm grid: trees, bridges, anything LoD2 lacks | 3.59 GB | 574.7 GB | zero |
| DOP10 JP2 | Aerial photo, 10 cm, with an infrared band: brightness, and plants versus paving | 5.61 GB | 1,174.6 GB | zero |
| Basis-DLM Shape | Water polygons; also forests and land use for the NRW overview | 4.69 GB, one statewide file | same file | zero |
| DVG1 Shape | City and state boundaries | 0.02 GB, one statewide file | same file | zero |

Bonn needs about 18 GB, which fits the 88 GB free on the laptop. NRW needs about 2 TB, which
doesn't, so it uses lighter sources (Phase 4). Bonn's sources line up well: all 224 DOP10 tiles and
196 of 224 nDOM50 tiles are from 2025, and the three photo tiles checked were flown on 2025-05-01,
when trees should be in leaf.

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

| Host | robots.txt | Use in this plan |
|---|---|---|
| `www.opengeodata.nrw.de` | Empty, so nothing is disallowed | All bulk downloads |
| `www.wms.nrw.de` | None | Phase 4 brightness, after the heads-up to Geobasis NRW |
| `www.gis.nrw.de` (3D-Mesh stream) | Disallows everything | Not used, unless Geobasis NRW agrees |
| `ckan.open.nrw.de` | Disallows `/api/` | Dataset pages only, read by a person |

## Scale, and why NRW is staged

Detail is measured in pixels per metre along the view's 2:1 axes. A tile is 512 × 512 px, so
tiles = area in m² × (px/m)² ÷ 262,144. Lower zoom levels add about a third more files.

| px/m | 10 m house is | Bonn city, 141 km² | All NRW, 34,110 km² | Note |
|---|---|---|---|---|
| 2.8 | ~57 px wide | ~4,300 tiles | ~1,040,000 tiles | Isometric NYC's level (~32,000 tiles in total); likely more than these rules can fill |
| **2** | **~40 px wide** | **~2,150 tiles** | ~520,000 tiles | **Default for Bonn and for cities** |
| 1.4 | ~28 px wide | ~1,050 tiles | ~255,000 tiles | Compared in Phase 0: chunkier pixels may read better |
| **0.5** | **~10 px wide** | ~135 tiles | **~32,500 tiles** | **Default for the NRW overview** |
| 0.25 | ~5 px wide | ~35 tiles | ~8,100 tiles | Fallback if free hosting runs short |

NRW at Isometric NYC's detail would be 32 times that whole project, so it can't be one job. Every
scale in use must be a power of 2 apart, so all regions share one pixel grid and line up exactly.
If Phase 0 picks 1.4 px/m for cities, the overview moves to 0.7 or 0.35 px/m.

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
   wrong. Each region is its own tile layer, so cities can be added one at a time and hosted separately.
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

| Phase | Work | Done when | Estimate |
|---|---|---|---|
| **0a. First picture** | Poppelsdorf, 1 km²: buildings and terrain in three looks side by side: flat material colours, photo brightness on material ramps, and a plain posterised photo as the comparison. No windows, water, trees, sprites or viewer. Kaya asks three members to draw one landmark each and asks the university's HPC team about free GPU use. | 3 of 5 members vote "game", not "GIS", for one look. | 2–3 evenings |
| **0b. Hard sites** | Altstadt, Bundesviertel with Post Tower, Kennedybrücke and Beuel, Venusberg and Kottenforst, a suburb. Add the height mesh, shadows, water and windows. Compare 2 with 1.4 px/m. Encode sample tiles to check size. | Members recognise the forest, suburb, bridge and tower. The seam test passes. One member's sprite is merged. | 1–2 weeks |
| **1. One district live** | About 10 km² from Altstadt to Poppelsdorf, end to end through publish. Test the deploy first with dummy files of Bonn's projected size. | A credited public link works on phone and laptop. KB per tile and tiles per second are measured, with all Bonn projected under 1 GB. Kaya can deploy in 15 minutes. | 2 weeks |
| **2. All Bonn** | City polygon from DVG1 with its edge drawn as a clear border, plus fixes from Phase 1. | Every km² reviewed by a member, with open bugs filed as issues with deep links. A rebuild from saved inputs matches tile hashes. The full deploy finishes inside Pages' 10-minute limit. | 2–3 weeks |
| **3. Landmarks, pins, robots, launch** | About 10 landmark sprites, Industry Map pins, robot scenes, a sprite-drawing evening. | Linked from robonn.de, with landmarks from at least 3 contributors. | 3 weeks |
| **4a. Köln region** | All of Regierungsbezirk Köln (Bonn, Köln, Aachen; about 7,400 km²) at 0.5 px/m, about 7,000 tiles. Tests the NRW method at a size that should fit one Pages site. | Bonn sits inside it, lined up exactly. KB per tile measured. | 3 weeks |
| **4b. All NRW** | The other four regions, with sector landmarks such as Duisburg's port, wind farms and research farms. Free hosting decided first. | The whole state pans and zooms within the host's limits. | 3–4 weeks |
| **5. NRW cities** | Cities added one at a time at 2 px/m, in order of Industry Map coverage and member interest. Köln city first, about 6,200 tiles. | The first city renders in one weekend. Then open-ended, until free hosting or interest runs out. | Per city |

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

### Phase 4 details

- **Sources stay light.** At 0.5 px/m the overview tries LoD1 flat-roof buildings (91.8 GB; licence to confirm)
  with DGM1 and Basis-DLM, about 175 GB downloaded and discarded per km² over several nights. Brightness comes
  from the state's orthophoto WMS at 2 m per pixel (about 36,000 requests and 6 GB, estimated) instead of 1.17 TB
  of full-resolution photos. Forests come from Basis-DLM polygons instead of 575 GB of nDOM50. Derived data
  should stay under 50 GB (estimate).
- **Be polite to the state's servers.** Kaya sends Geobasis NRW a short heads-up before bulk downloads.
- **Hosting decision, using the size measured in Phase 4a.** The whole overview likely exceeds GitHub Pages' 1 GB
  site limit. Options to compare then:
  - one site per Regierungsbezirk, on GitHub Pages (1 GB each) or Cloudflare Pages (20,000 files each; its terms
    on image-heavy sites need checking);
  - Cloudflare R2's free tier (10 GB, no egress fees; sources conflict on whether a card must be on file, which is
    Kaya's call);
  - the existing Hetzner webspace, if its quota allows;
  - dropping the overview to 0.25 px/m (about 8,100 tiles).
- **What zooming looks like.** Past the overview's detail, areas outside a detailed city show bigger pixels. A
  city's edge is drawn as a clear outline, so a detailed city reads as "unlocked". That also gives members a reason
  to unlock the next one.

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

| Risk | Earliest signal | Response |
|---|---|---|
| It reads as a posterised GIS render, not pixel art | 0a vote | Another of the three looks, one more style round, then the three options above |
| Nobody draws sprites | 0a request to three members | A smaller landmark set from the core team; generated sprites in the Pixel view's manner; AI drafts if a GPU comes |
| Volunteer time runs out | Phase 1 slips past 4 weeks | Bonn alone is a complete result; NRW stays optional |
| Forests and suburbs look dull | 0b sites | More ramp steps; tree sprites |
| The height mesh gives melted trees, or noise on streets and water | 0b Kottenforst and Kennedybrücke | Filtering; forests stay as mesh, open-ground trees become sprites at nDOM50 peaks, with infrared filtering out trucks and cranes |
| The bridge deck is wrong in the height mesh | 0b Kennedybrücke | Hand-built deck using DGM1 and nDOM50 heights |
| DOP10 roofs lean away from their footprints, so roof detail picks up walls or ground | 0b Bundesviertel | Tall roofs take a flat colour family and no photo brightness |
| Windows look messy on walls that don't follow the pixel grid | 0b sites | Simplify them, or drop them on those walls |
| Basis-DLM polygons are too coarse or don't line up | 0b Kennedybrücke | Cadastre land use (`lk/akt/gru_vereinfacht_gpkg`, licence zero, parcels without owners) |
| Headless rendering fails on the laptop's two GPUs | First hour of 0a | Mesa on the CPU (slower), or headless three.js at the cost of Chromium's memory |
| Bonn exceeds 1 GB on GitHub Pages | 0b sample, then Phase 1 | Lower px/m, or crop to the city polygon |
| The laptop is short on memory (about 3 GB free when checked) | 0a | Work one km² at a time; run while other jobs are stopped |
| NRW photos span 2022 to 2026, so brightness jumps at flight-block edges | Phase 4a | Colour ramps limit this; match brightness per block and accept what remains |

## Repo layout

Follows the sibling projects' pattern.

```
projects/isometric-bonn/
  building-plan.md
  README.md  LICENSE  LICENSE-ART  CONTRIBUTING.md  references-examples.md  SOURCES.md
  pyproject.toml  uv.lock
  regions/bonn.yaml  regions/koeln.yaml  regions/nrw.yaml   # boundary, scale: same code, new config
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
- **Licences:** each source's licence is recorded in `SOURCES.md`, with DGM1 and LoD1 confirmed there.
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
  [orthophoto WMS](https://www.wms.nrw.de/geobasis/wms_nw_dop?REQUEST=GetCapabilities&SERVICE=WMS),
  [simplified cadastre](https://ckan.open.nrw.de/sl/dataset/3e8cf42f-7faa-4bee-b71a-fc6c01d26213),
  [licence dl-de/zero-2-0](https://www.govdata.de/dl-de/zero-2-0)
- [Bonn tree register](https://opendata.bonn.de/dataset/baumstandorte)
- [GitHub Pages limits](https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits),
  [Cloudflare Pages limits](https://developers.cloudflare.com/pages/platform/limits/),
  [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [Uni Bonn HPC systems](https://www.hpc.uni-bonn.de/en/systems/marvin),
  [Qwen-Image-Edit](https://huggingface.co/Qwen/Qwen-Image-Edit)
