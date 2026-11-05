#!/usr/bin/env python3
"""Rebuild the fictional README demo from a fixed seed.

Picks countries, US states, Chinese provinces, and Japanese prefectures at
random, drops city dots at random coordinates inside those shapes, and writes
demo/travel.yml plus the preview PNGs, SVGs, and stats badge. Nothing in that file is a real
itinerary. Sensitive and disputed countries are left out, and so are Xinjiang,
Tibet, and Inner Mongolia. ``--out`` writes the same files somewhere else and
leaves the committed demo alone.

    python3 scripts/make_demo.py
    python3 scripts/make_demo.py --out /tmp/travel-demo
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import warnings
from datetime import date
from pathlib import Path

from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from footprint import (  # noqa: E402
    BADGE_FILENAME,
    City,
    TravelConfig,
    load_world,
    parse_config,
    read_admin0,
    read_admin1_china,
    read_admin1_japan,
    read_admin1_usa,
    render_maps,
    render_png,
    render_svg,
    resolve_travel,
)

# Same seed always rebuilds the same places and the same PNGs.
SEED = 20261102
STATE_COUNT = 10
CITY_COUNT = 50
PROVINCE_COUNT = 4
PREFECTURE_COUNT = 4
# Square degrees. A province or prefecture smaller than this disappears on the world map.
MIN_PROVINCE_AREA = 8.0
MIN_PREFECTURE_AREA = 1.0
# Square degrees in the source CRS. Small islands disappear on the world map.
MIN_AREA = 8.0
# A day that is neither Halloween nor Christmas. The demo palette is explicit.
DEMO_DAY = date(2026, 6, 1)

# How many countries to take from each continent, in this order. The sum is
# the demo's country count (32), inside the 25-35 range.
CONTINENT_QUOTAS: tuple[tuple[str, int], ...] = (
    ("Africa", 7),
    ("Asia", 7),
    ("Europe", 6),
    ("North America", 4),
    ("South America", 5),
    ("Oceania", 3),
)

# Natural Earth marks some units Disputed or Indeterminate; those are skipped
# too. This list is the additional set of places the sample must not use.
EXCLUDED_COUNTRIES = frozenset(
    {
        "AFG",  # Afghanistan
        "BLR",  # Belarus
        "CUB",  # Cuba
        "CYN",  # N. Cyprus
        "ESH",  # Western Sahara
        "IRN",  # Iran
        "IRQ",  # Iraq
        "ISR",  # Israel
        "KOS",  # Kosovo
        "LBY",  # Libya
        "MMR",  # Myanmar
        "PRK",  # North Korea
        "PSE",  # Palestine
        "PSX",  # Palestine
        "RUS",  # Russia
        "SAH",  # Western Sahara
        "SDN",  # Sudan
        "SDS",  # South Sudan
        "SSD",  # South Sudan
        "SOL",  # Somaliland
        "SYR",  # Syria
        "TWN",  # Taiwan
        "UKR",  # Ukraine
        "VEN",  # Venezuela
        "YEM",  # Yemen
    }
)
DISPUTED_TYPES = frozenset({"Disputed", "Indeterminate"})

# The demo draws these as subdivisions, so the seeded country sample must not
# also fill them in full. If the seed picked one, it is swapped for another
# country on the same continent.
SUBDIVISION_COUNTRIES = frozenset({"CHN", "JPN"})

# Real admin units the sample must not use. The renderer still accepts them.
EXCLUDED_PROVINCES = frozenset({"Xinjiang", "Xizang", "Inner Mongol"})


def _clamp(lon: float, lat: float) -> tuple[float, float]:
    lon = min(180.0, max(-180.0, round(lon, 4)))
    lat = min(90.0, max(-90.0, round(lat, 4)))
    return lon, lat


def _random_point(rng: random.Random, geom) -> tuple[float, float]:
    """A seeded point inside ``geom``, in unprojected longitude and latitude."""
    if not geom.is_valid:
        geom = geom.buffer(0)
    minx, miny, maxx, maxy = geom.bounds
    if maxx - minx <= 300:
        for _ in range(400):
            lon = rng.uniform(minx, maxx)
            lat = rng.uniform(miny, maxy)
            if geom.covers(Point(lon, lat)):
                return _clamp(lon, lat)
    point = geom.representative_point()
    return _clamp(float(point.x), float(point.y))


def _separated_point(rng: random.Random, geom, placed: list[tuple[float, float]]) -> tuple[float, float]:
    """A point inside ``geom`` that is not on top of one already chosen."""
    for _ in range(40):
        lon, lat = _random_point(rng, geom)
        if all(abs(lon - other_lon) + abs(lat - other_lat) > 4 for other_lon, other_lat in placed):
            return lon, lat
    return _random_point(rng, geom)


def _areas(frame) -> dict[str, float]:
    return {str(name): float(area) for name, area in zip(frame["name"], frame.geometry.area)}


def synthetic_config(rng: random.Random | None = None) -> TravelConfig:
    """Random fictional places. The default generator is ``random.Random(SEED)``."""
    rng = random.Random(SEED) if rng is None else rng
    countries = read_admin0()
    states = read_admin1_usa()
    provinces = read_admin1_china()
    prefectures = read_admin1_japan()
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Geometry is in a geographic CRS")
        area_by_code = {
            code: float(area)
            for code, area in zip(countries["adm0_a3"], countries.geometry.area)
        }
        province_area = _areas(provinces)
        prefecture_area = _areas(prefectures)
    pools: dict[str, list[str]] = {name: [] for name, _quota in CONTINENT_QUOTAS}
    continent_of: dict[str, str] = {}
    for row in countries.itertuples(index=False):
        code = str(row.adm0_a3)
        continent_of[code] = str(row.CONTINENT)
        if code == "USA" or code in EXCLUDED_COUNTRIES:
            continue
        if str(row.TYPE) in DISPUTED_TYPES:
            continue
        if area_by_code[code] <= MIN_AREA:
            continue
        if row.CONTINENT in pools:
            pools[row.CONTINENT].append(code)
    chosen: list[str] = []
    for continent, quota in CONTINENT_QUOTAS:
        pool = sorted(set(pools[continent]))
        if len(pool) < quota:
            raise RuntimeError(
                f"only {len(pool)} {continent} countries are available for the demo; need {quota}"
            )
        chosen.extend(rng.sample(pool, quota))
    chosen_countries = sorted(chosen)
    state_names = sorted(name for name in states["name"].unique())
    if len(state_names) < STATE_COUNT:
        raise RuntimeError(f"only {len(state_names)} US states are available for the demo")
    chosen_states = sorted(rng.sample(state_names, STATE_COUNT))

    by_country = {row.adm0_a3: row.geometry for row in countries.itertuples(index=False)}
    by_state = {row.name: row.geometry for row in states.itertuples(index=False)}
    extra_countries = sorted(chosen_countries, key=lambda code: (-area_by_code[code], code))[
        : CITY_COUNT - len(chosen_countries) - len(chosen_states)
    ]
    cities: list[City] = []
    placed: list[tuple[float, float]] = []

    def add_city(geom) -> None:
        lon, lat = _separated_point(rng, geom, placed)
        placed.append((lon, lat))
        cities.append(City(f"Site {len(cities) + 1:02d}", lat, lon))

    extras = set(extra_countries)
    for code in chosen_countries:
        add_city(by_country[code])
        if code in extras:
            add_city(by_country[code])
    for name in chosen_states:
        add_city(by_state[name])

    # China and Japan are drawn as subdivisions. Swap either one out of the
    # filled-country list after the seeded sample so the other countries,
    # states, and cities stay put, and the continent counts stay the same.
    chosen_countries = list(chosen_countries)
    for code in [item for item in chosen_countries if item in SUBDIVISION_COUNTRIES]:
        continent = continent_of[code]
        chosen_countries.remove(code)
        pool = sorted(
            candidate
            for candidate in pools[continent]
            if candidate not in chosen_countries and candidate not in SUBDIVISION_COUNTRIES
        )
        if not pool:
            raise RuntimeError(f"no replacement {continent} country for {code}")
        replacement = rng.choice(pool)
        chosen_countries.append(replacement)
        add_city(by_country[replacement])
    chosen_countries = sorted(chosen_countries)

    province_pool = sorted(
        name
        for name, area in province_area.items()
        if name not in EXCLUDED_PROVINCES and area >= MIN_PROVINCE_AREA
    )
    if len(province_pool) < PROVINCE_COUNT:
        raise RuntimeError(
            f"only {len(province_pool)} Chinese provinces are available for the demo"
        )
    chosen_provinces = sorted(rng.sample(province_pool, PROVINCE_COUNT))

    # Hokkaido is the prefecture large enough to read on this world map.
    # Also keep any prefecture that already contains a demo city.
    pinned = [max(prefecture_area, key=prefecture_area.get)]
    pref_geoms = {row.name: row.geometry for row in prefectures.itertuples(index=False)}
    for city in cities:
        point = Point(city.lon, city.lat)
        for name, geom in pref_geoms.items():
            if geom is not None and not geom.is_empty and geom.covers(point):
                if name not in pinned:
                    pinned.append(name)
                break
    if len(pinned) > PREFECTURE_COUNT:
        raise RuntimeError(
            f"{len(pinned)} demo cities already sit in Japanese prefectures; "
            f"the demo only draws {PREFECTURE_COUNT}"
        )
    pref_pool = sorted(
        name
        for name, area in prefecture_area.items()
        if area >= MIN_PREFECTURE_AREA and name not in pinned
    )
    need = PREFECTURE_COUNT - len(pinned)
    if len(pref_pool) < need:
        raise RuntimeError(
            f"only {len(pref_pool)} Japanese prefectures are available for the demo"
        )
    chosen_prefectures = sorted(pinned + rng.sample(pref_pool, need))

    if not (40 <= len(cities) <= 60):
        raise RuntimeError(f"demo city count is {len(cities)}, expected 40 to 60")
    return TravelConfig(
        countries=tuple(chosen_countries),
        us_states=tuple(chosen_states),
        china_provinces=tuple(chosen_provinces),
        japan_prefectures=tuple(chosen_prefectures),
        cities=tuple(cities),
    )


def _yaml_scalar(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9]+", value):
        return value
    return json.dumps(value, ensure_ascii=False)


def dump_config(config: TravelConfig) -> str:
    """Stable YAML for the demo file, including the seed it came from."""
    lines = [
        f"# Fictional demo places. scripts/make_demo.py rebuilds this file from seed {SEED}.",
        "# These are not a real itinerary.",
        "countries:",
    ]
    for code in config.countries:
        lines.append(f"  - {_yaml_scalar(code)}")
    lines.append("us_states:")
    for name in config.us_states:
        lines.append(f"  - {_yaml_scalar(name)}")
    lines.append("china_provinces:")
    for name in config.china_provinces:
        lines.append(f"  - {_yaml_scalar(name)}")
    lines.append("japan_prefectures:")
    for name in config.japan_prefectures:
        lines.append(f"  - {_yaml_scalar(name)}")
    lines.append("cities:")
    for city in config.cities:
        lines.append(f"  - name: {_yaml_scalar(city.name)}")
        lines.append(f"    lat: {city.lat:.4f}")
        lines.append(f"    lon: {city.lon:.4f}")
    lines.append("")
    return "\n".join(lines)


def render_demo(config_path: Path, out_dir: Path) -> TravelConfig:
    """Render the default dark/light pair, a Christmas dark map, and the stats badge.

    The badge uses the same fictional config and the default palette. It is
    not a real itinerary.
    """
    text = config_path.read_text(encoding="utf-8")
    config = parse_config(text, path=str(config_path))
    render_maps(config, out_dir, "default", DEMO_DAY, image_format="both", badge=True)
    world = load_world()
    resolved = resolve_travel(config, world)
    render_png(world, resolved, "dark", "christmas", out_dir / "travel-map-christmas.png")
    render_svg(world, resolved, "dark", "christmas", out_dir / "travel-map-christmas.svg")
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rebuild the fictional README demo from a fixed seed.")
    parser.add_argument(
        "--out",
        type=Path,
        help="Directory for travel.yml, the maps, and the stats badge. Defaults to demo/.",
    )
    args = parser.parse_args(argv)
    out = ROOT / "demo" if args.out is None else args.out
    out.mkdir(parents=True, exist_ok=True)
    text = dump_config(synthetic_config())
    config_path = out / "travel.yml"
    config_path.write_text(text, encoding="utf-8")
    render_demo(config_path, out)
    print(f"demo seed={SEED} config={config_path} badge={out / BADGE_FILENAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
