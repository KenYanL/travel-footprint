# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Reusable composite action and `travel_footprint.py` CLI that render a Pacific-centred world map from a YAML file of countries, US states, and cities. Writes `travel-map.png` (dark) and `travel-map-light.png` (light).
- `china_provinces` and `japan_prefectures`. A listed province, autonomous region, municipality, or prefecture is filled on its own; the rest of that country stays plain land. Names accept the Natural Earth English name or an ISO 3166-2 code. An unknown name fails with a suggestion when one is close. Listing `China` or `Japan` under `countries` still fills that country entirely, and the subdivision list is not drawn on top.
- Japanese prefectures from a public-domain Natural Earth 1:10m admin-1 extract in `data/`. The vendored 1:50m admin-1 file has Chinese provinces and US states, and it does not include Japan.
- Palettes `default`, `halloween`, `christmas`, and `auto`. `auto` uses Halloween on 31 October (UTC), Christmas on 24, 25, and 26 December (UTC), and the green map every other day.
- Vendored Natural Earth 1:50m admin-0 and admin-1 extracts, with a download cache and sha256 check when the files are absent.
- Pytest coverage for config validation, palette dates, and a smoke render. The CI workflow runs those tests on pull requests.
- Fictional README demo in `demo/`, rebuilt by `scripts/make_demo.py` from a fixed seed.

### Changed

- Listing US states paints only those states. The rest of the United States stays the plain land color, including Alaska and every state that was not listed. The lighter whole-country tint is gone. A country listed under `countries` still fills entirely.
- Christmas visited regions use diagonal stripes: red `#bc4749` with green `#6a994e`, 8 pixels per band at the output resolution, clipped to the visited shapes. City dots stay `#f2e8cf`. Default and Halloween stay solid fills.
- The fictional demo is a larger seeded sample, spread across every continent, and it skips disputed territories plus a fixed list of sensitive countries.
