"""The README demo is a fixed fictional seed, not a hand-written itinerary."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from make_demo import (  # noqa: E402
    CONTINENT_QUOTAS,
    DISPUTED_TYPES,
    EXCLUDED_COUNTRIES,
    SEED,
    dump_config,
    synthetic_config,
)
from footprint import read_admin0  # noqa: E402


def test_demo_seed_is_stable() -> None:
    assert dump_config(synthetic_config()) == dump_config(synthetic_config())


def test_committed_demo_matches_the_generator() -> None:
    committed = (ROOT / "demo" / "travel.yml").read_text(encoding="utf-8")
    assert committed == dump_config(synthetic_config())
    assert f"seed {SEED}" in committed
    assert "not a real itinerary" in committed


def test_demo_places_are_generated_labels() -> None:
    config = synthetic_config()
    assert 25 <= len(config.countries) <= 35
    assert 8 <= len(config.us_states) <= 12
    assert 40 <= len(config.cities) <= 60
    assert [city.name for city in config.cities] == [
        f"Site {number:02d}" for number in range(1, len(config.cities) + 1)
    ]
    assert "USA" not in config.countries
    assert EXCLUDED_COUNTRIES.isdisjoint(config.countries)
    for city in config.cities:
        assert -90 <= city.lat <= 90
        assert -180 <= city.lon <= 180


def test_demo_spans_continents_and_skips_disputed_places() -> None:
    config = synthetic_config()
    countries = read_admin0()
    by_code = {row.adm0_a3: row for row in countries.itertuples(index=False)}
    seen: dict[str, int] = {}
    for code in config.countries:
        row = by_code[code]
        assert str(row.TYPE) not in DISPUTED_TYPES
        seen[row.CONTINENT] = seen.get(row.CONTINENT, 0) + 1
    for continent, quota in CONTINENT_QUOTAS:
        assert seen.get(continent) == quota


def test_demo_images_are_committed() -> None:
    demo = ROOT / "demo"
    for name in ("travel-map.png", "travel-map-light.png", "travel-map-christmas.png"):
        path = demo / name
        assert path.is_file(), name
        assert path.stat().st_size > 8_000
