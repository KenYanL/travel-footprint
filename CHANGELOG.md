# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Palette `newyear`. Color Hunt gold gradient ([source](https://colorhunt.co/palette/f9e6a8f2a900cc6f004d2a00): `#f9e6a8`, `#f2a900`, `#cc6f00`, `#4d2a00`). Visited regions use amber `#cc6f00` with dark-brown `#4d2a00` diagonal stripes and pale-gold `#f9e6a8` dots, the same striped style as Christmas. `#f2a900` is unused in the map ink. `auto` selects it on 1 January (UTC). SVG stripe pattern ids are now `{palette}-stripes` (for example `newyear-stripes`). Demo assets `demo/travel-map-newyear.png` and `demo/travel-map-newyear.svg` are included.
- Packaging prep for the CLI. `pyproject.toml` builds `travel-footprint` 0.1.0 with a `travel-footprint` console script and the Natural Earth files inside the package. CI runs `python -m build` and checks that the sdist and wheel exist. The package is not published on PyPI.
- `planned` and `planned_states`. Planned cities use the same shape as `cities`, and planned US states accept a name or USPS code. They are drawn in the palette accent and are not counted as visited. In SVG they pulse with SMIL on a 1.8s loop: a planned state fades between opacity 0.25 and 0.6 with a dashed outline, and a planned city shows an expanding ring plus a dot. PNG keeps that fill and dot static. Configs that omit the keys are unchanged. Planned places are left out of the stats badge.
- Stats badge `travel-badge.svg`, written next to the map. It is on by default. `--badge false`, or the action input `badge: false`, skips it. The badge is a self-contained SVG with no network request. It shows countries visited, that count as a percent of the countries the map can draw, and US states. China provinces and Japan prefectures are included when those units are drawn. Colors follow the active palette: default green `#3fb950`, Halloween orange `#c46212` with yellow `#e3d04f`, Christmas red `#bc4749` with green `#6a994e` and cream `#f2e8cf`, and New Year amber `#cc6f00` with brown `#4d2a00` and pale gold `#f9e6a8`. The map files are unchanged. Planned states and planned cities are not included in these counts.
- SVG output. `--format svg` writes `travel-map.svg` and `travel-map-light.svg`. `--format both` writes those beside the PNGs. The default stays `png`, so existing runs still write only the two PNGs. The action input is `format`, with `map_dark_svg_path` and `map_light_svg_path` set when an SVG is written. Christmas stripes are an SVG pattern: visited regions stay `#bc4749` with `#6a994e` 8px diagonal bands and `#f2e8cf` dots. Default and Halloween stay solid fills.
- Reusable composite action and `travel_footprint.py` CLI that render a Pacific-centred world map from a YAML file of countries, US states, and cities. Writes `travel-map.png` (dark) and `travel-map-light.png` (light).
- `china_provinces` and `japan_prefectures`. A listed province, autonomous region, municipality, or prefecture is filled on its own; the rest of that country stays plain land. Names accept the Natural Earth English name or an ISO 3166-2 code. An unknown name fails with a suggestion when one is close. Listing `China` or `Japan` under `countries` still fills that country entirely, and the subdivision list is not drawn on top.
- Japanese prefectures from a public-domain Natural Earth 1:10m admin-1 extract in `data/`. The vendored 1:50m admin-1 file has Chinese provinces and US states, and it does not include Japan.
- Palettes `default`, `halloween`, `christmas`, `newyear`, and `auto`. `auto` uses New Year on 1 January (UTC), Halloween on 31 October (UTC), Christmas on 24, 25, and 26 December (UTC), and the green map every other day.
- Vendored Natural Earth 1:50m admin-0 and admin-1 extracts, with a download cache and sha256 check when the files are absent.
- Pytest coverage for config validation, palette dates, and a smoke render. The CI workflow runs those tests on pull requests.
- Fictional README demo in `demo/`, rebuilt by `scripts/make_demo.py` from a fixed seed.

### Changed

- Listing US states paints only those states. The rest of the United States stays the plain land color, including Alaska and every state that was not listed. The lighter whole-country tint is gone. A country listed under `countries` still fills entirely.
- Christmas visited regions use diagonal stripes: red `#bc4749` with green `#6a994e`, 8 pixels per band at the output resolution, clipped to the visited shapes. City dots stay `#f2e8cf`. Default and Halloween stay solid fills.
- The fictional demo is a larger seeded sample, spread across every continent, and it skips disputed territories plus a fixed list of sensitive countries.
