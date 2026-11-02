"""The README demo is a fixed fictional seed, not a hand-written itinerary."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from make_demo import SEED, dump_config, synthetic_config  # noqa: E402


def test_demo_seed_is_stable() -> None:
    assert dump_config(synthetic_config()) == dump_config(synthetic_config())


def test_committed_demo_matches_the_generator() -> None:
    committed = (ROOT / "demo" / "travel.yml").read_text(encoding="utf-8")
    assert committed == dump_config(synthetic_config())
    assert f"seed {SEED}" in committed
    assert "not a real itinerary" in committed


def test_demo_places_are_generated_labels() -> None:
    config = synthetic_config()
    assert len(config.countries) == 6
    assert len(config.us_states) == 5
    assert len(config.cities) == 11
    assert [city.name for city in config.cities] == [f"Site {number:02d}" for number in range(1, 12)]
    assert "USA" not in config.countries
    for city in config.cities:
        assert -90 <= city.lat <= 90
        assert -180 <= city.lon <= 180


def test_demo_images_are_committed() -> None:
    demo = ROOT / "demo"
    for name in ("travel-map.png", "travel-map-light.png", "travel-map-christmas.png"):
        path = demo / name
        assert path.is_file(), name
        assert path.stat().st_size > 8_000
