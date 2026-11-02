# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Reusable composite action and `travel_footprint.py` CLI that render a Pacific-centred world map from a YAML file of countries, US states, and cities. Writes `travel-map.png` (dark) and `travel-map-light.png` (light).
- Palettes `default`, `halloween`, `christmas`, and `auto`. `auto` uses Halloween on 31 October (UTC), Christmas on 24, 25, and 26 December (UTC), and the green map every other day.
- Vendored Natural Earth 1:50m admin-0 and admin-1 extracts, with a download cache and sha256 check when the files are absent.
- Pytest coverage for config validation, palette dates, and a smoke render. The CI workflow runs those tests on pull requests.
- Fictional README demo in `demo/`, rebuilt by `scripts/make_demo.py` from a fixed seed.
