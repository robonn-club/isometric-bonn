# Sources

Every file the map is built from, where it comes from and under which licence. The exact files
used, with size, timestamp and SHA-256, are listed in [`data/manifest.json`](data/manifest.json).

## In use

All from [OpenGeodata.NRW](https://www.opengeodata.nrw.de/produkte/geobasis/), owner Land
Nordrhein-Westfalen, Bezirksregierung Köln, Geobasis NRW. EPSG:25832, heights in DHHN2016.

| Product | What we take from it | Files | Survey date (product metadata) | Licence |
| --- | --- | --- | --- | --- |
| LoD2 CityGML | Roofs, walls and ground footprints; building function and height. Addresses are never read. | `LoD2_32_<e>_<n>_1_NW.gml`; 247 tiles for all of Bonn | file timestamps 2026-05-26 | dl-de/zero-2-0 |
| DGM1 GeoTIFF | Bare-ground height, 1 m grid | `dgm1_32_…_1_nw_2021.tif` | 2021-12-22 (`dgm1_meta.zip`) | dl-de/zero-2-0 expected; **to confirm** |
| nDOM50 GeoTIFF | Height above ground, 0.5 m grid: tree crowns | `ndom50_32…_1_nw_2025.tif` | surface 2025-05-01, ground 2021-12-22 (`ndom50_meta.zip`) | dl-de/zero-2-0 expected; **to confirm** |
| DOP10 JPEG 2000 | Aerial photo, red, green, blue and infrared, read at 40 cm | `dop10rgbi_32_…_1_nw_2025.jp2` | flown 2025-05-01, rectified on the image-based surface model (`dop_meta.zip`) | dl-de/zero-2-0 expected; **to confirm** |
| DVG1 Shape | Bonn's city boundary (municipality key 05314000, `dvg1gem_nw`) | `dvg1_EPSG25832_Shape.zip`, one statewide file | boundaries as of 2025-11-12 | dl-de/zero-2-0 expected; **to confirm** |
| ALKIS Grundrissdaten vereinfacht (GeoPackage) | Land use only (layer `Nutzung`: road, path, rail, water, forest type, field, park, sports, cemetery). The parcel layers and every address column are never read. | `gru_vereinf_05314000_Bonn_EPSG25832_GeoPackage.zip` | land use updated 2024-10-15 to 2026-06-30 | dl-de/zero-2-0 expected; **to confirm** |

**To confirm:** the products' metadata files (`*_meta.zip`, read 2026-11-11) list owner, dates and
camera but carry no licence field. The licence for DGM1, nDOM50, DOP10, DVG1 and the cadastre still needs a person to
read it on the products' pages (the plan's Phase 0 task). The licence text:
[Datenlizenz Deutschland – Zero – Version 2.0](https://www.govdata.de/dl-de/zero-2-0). It sets no
conditions, so a credit is optional; the map credits Geobasis NRW anyway.

## Planned, not yet used

| Source | For | Note |
| --- | --- | --- |
| Bonn tree register (opendata.bonn.de, CC0) | Optional tree positions | Its endpoint returned 504 on 2026-11-07. |

## Not used

- **OpenStreetMap:** not needed for the picture, which avoids ODbL duties.
- **3D-Mesh NW:** kept for a possible AI upgrade only; its streaming host disallows robots.
- **Google 3D tiles:** their terms restrict caching, offline use and derived works.

## Automated access

The downloader reads each host's robots.txt before the first request and obeys it for its own
User-Agent and, when run from a Claude Code session, for Claude's agents too.
`www.opengeodata.nrw.de` serves an empty robots.txt (read 2026-11-11), so nothing is disallowed.
Downloads run one at a time.

## Credit

Reference for the idea: [Isometric NYC](https://isometric.nyc). No code, images
or tiles from it are used. The palette starts from the club's Rhein palette and the Industry
Map's Pixel view. Fonts: Outfit and Manrope, SIL Open Font License 1.1 (`viewer/fonts/`).
