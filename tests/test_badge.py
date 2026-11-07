"""The stats badge: counts, palette colors, and a self-contained SVG."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest

from footprint import (
    BADGE_FILENAME,
    PALETTES,
    InputError,
    TravelStats,
    badge_document,
    badge_message,
    parse_badge,
    parse_config,
    percent_of_world,
    render_maps,
    travel_stats,
    world_country_total,
)
from travel_footprint import main

ROOT = Path(__file__).resolve().parents[1]
NS = "{http://www.w3.org/2000/svg}"
DAY = date(2026, 6, 1)


@pytest.fixture(scope="module")
def world():
    from footprint import load_world

    return load_world()


def test_percent_rounds_to_the_nearest_tenth() -> None:
    assert percent_of_world(0, 241) == "0%"
    assert percent_of_world(1, 241) == "0.4%"
    assert percent_of_world(3, 241) == "1.2%"
    assert percent_of_world(32, 241) == "13.3%"
    assert percent_of_world(241, 241) == "100%"
    assert percent_of_world(1, 2000) == "0.1%"
    with pytest.raises(Exception):
        percent_of_world(-1, 241)
    with pytest.raises(Exception):
        percent_of_world(1, 0)


def test_parse_badge_accepts_true_and_false_only() -> None:
    assert parse_badge("true") is True
    assert parse_badge(" TRUE ") is True
    assert parse_badge("false") is False
    assert parse_badge("False") is False
    for raw in ("", "   ", "yes", "no", "1", "0", "on", "off"):
        with pytest.raises(InputError, match="badge"):
            parse_badge(raw)
    with pytest.raises(InputError, match="badge"):
        parse_badge(True)


def test_china_and_japan_are_omitted_until_drawn() -> None:
    stats = TravelStats(
        countries=2,
        world_countries=241,
        us_states=0,
        china_provinces=0,
        japan_prefectures=0,
    )
    message = badge_message(stats)
    assert message == "2 countries · 0.8% of world · 0 US states"
    assert "China" not in message
    assert "Japan" not in message

    singular = TravelStats(
        countries=1,
        world_countries=241,
        us_states=1,
        china_provinces=1,
        japan_prefectures=1,
    )
    assert badge_message(singular) == (
        "1 country · 0.4% of world · 1 US state · 1 China province · 1 Japan prefecture"
    )


def _parse(path: Path) -> tuple[str, ET.Element]:
    text = path.read_text(encoding="utf-8")
    root = ET.fromstring(text)
    assert root.tag == f"{NS}svg"
    return text, root


def _part(root: ET.Element, name: str) -> ET.Element:
    found = [element for element in root.iter() if element.get("data-part") == name]
    assert len(found) == 1
    return found[0]


def _assert_self_contained(text: str) -> None:
    assert text.startswith("<?xml")
    assert "http://www.w3.org/2000/svg" in text
    without_namespace = text.replace("http://www.w3.org/2000/svg", "")
    assert "http://" not in without_namespace
    assert "https://" not in without_namespace
    assert "href" not in text
    assert "<script" not in text
    assert "<image" not in text
    assert "foreignObject" not in text


def _assert_text_fits(root: ET.Element, text_part: str, rect_part: str) -> None:
    label = _part(root, text_part)
    rect = _part(root, rect_part)
    center = float(label.get("x"))
    length = float(label.get("textLength"))
    left = center - length / 2
    right = center + length / 2
    origin = float(rect.get("x") or 0)
    width = float(rect.get("width"))
    assert left >= origin + 4
    assert right <= origin + width - 4


def test_badge_svg_uses_the_palette_and_fits_its_text(world, tmp_path: Path) -> None:
    config = parse_config(
        "countries:\n  - NZ\n  - CL\n"
        "us_states:\n  - WY\n"
        "china_provinces:\n  - Sichuan\n"
        "japan_prefectures:\n  - Kyoto\n",
        path="badge.yml",
    )
    result = render_maps(config, tmp_path / "dist", "default", DAY, world=world, badge=True)
    assert result.badge_path == tmp_path / "dist" / BADGE_FILENAME
    text, root = _parse(result.badge_path)
    _assert_self_contained(text)
    assert root.get("height") == "20"
    assert "2 countries" in text
    assert "1 US state" in text
    assert "1 China province" in text
    assert "1 Japan prefecture" in text
    assert f"of {world_country_total(world)} world countries" in text
    assert _part(root, "value-bg").get("fill") == PALETTES["default"]["dark"]["visited"]
    assert _part(root, "label-bg").get("fill") == "#0d1117"
    assert _part(root, "label").text == "visited"
    assert 'textLength="36.75"' in text
    _assert_text_fits(root, "label", "label-bg")
    _assert_text_fits(root, "value", "value-bg")
    assert "#c46212" not in text
    assert "#bc4749" not in text


def test_halloween_and_christmas_badges_follow_those_palettes(world, tmp_path: Path) -> None:
    config = parse_config("countries:\n  - NZ\n", path="nz.yml")
    halloween = render_maps(
        config, tmp_path / "halloween", "halloween", DAY, world=world, image_format="svg"
    )
    christmas = render_maps(
        config,
        tmp_path / "christmas",
        "auto",
        date(2026, 12, 25),
        world=world,
        image_format="svg",
    )
    assert halloween.palette == "halloween"
    assert christmas.palette == "christmas"
    halloween_text, halloween_root = _parse(halloween.badge_path)
    christmas_text, christmas_root = _parse(christmas.badge_path)
    assert _part(halloween_root, "value-bg").get("fill") == "#c46212"
    assert _part(halloween_root, "label").get("fill") == "#e3d04f"
    assert _part(halloween_root, "value").get("fill") == "#ffffff"
    assert "#3fb950" not in halloween_text
    assert _part(christmas_root, "label-bg").get("fill") == "#6a994e"
    assert _part(christmas_root, "value-bg").get("fill") == "#bc4749"
    assert _part(christmas_root, "value").get("fill") == "#f2e8cf"
    assert "#3fb950" not in christmas_text
    assert "#c46212" not in christmas_text
    _assert_self_contained(halloween_text)
    _assert_self_contained(christmas_text)


def test_newyear_badge_follows_that_palette(world, tmp_path: Path) -> None:
    config = parse_config("countries:\n  - NZ\n", path="nz.yml")
    newyear = render_maps(
        config,
        tmp_path / "newyear",
        "auto",
        date(2026, 1, 1),
        world=world,
        image_format="svg",
    )
    assert newyear.palette == "newyear"
    text, root = _parse(newyear.badge_path)
    assert _part(root, "label-bg").get("fill") == "#4d2a00"
    assert _part(root, "value-bg").get("fill") == "#cc6f00"
    assert _part(root, "value").get("fill") == "#f9e6a8"
    assert _part(root, "label").get("fill") == "#f9e6a8"
    assert "#3fb950" not in text
    assert "#bc4749" not in text
    assert "#c46212" not in text
    _assert_self_contained(text)


def test_badge_false_skips_the_file_and_keeps_the_map_bytes(world, tmp_path: Path) -> None:
    config = parse_config("countries:\n  - NZ\nus_states:\n  - WY\n", path="nz.yml")
    off = render_maps(
        config, tmp_path / "off", "default", DAY, world=world, image_format="both", badge=False
    )
    on = render_maps(
        config, tmp_path / "on", "default", DAY, world=world, image_format="both", badge=True
    )
    assert off.badge_path is None
    assert not (tmp_path / "off" / BADGE_FILENAME).exists()
    assert on.badge_path.is_file()
    assert off.dark_path.read_bytes() == on.dark_path.read_bytes()
    assert off.light_path.read_bytes() == on.light_path.read_bytes()
    assert off.dark_svg_path.read_bytes() == on.dark_svg_path.read_bytes()
    assert off.light_svg_path.read_bytes() == on.light_svg_path.read_bytes()


def test_planned_places_are_left_out_of_badge_stats(world, tmp_path: Path) -> None:
    """A planned state and city are drawn. The badge stays on the visited counts."""
    visited_text = (
        "countries:\n  - NZ\n"
        "us_states:\n  - WY\n"
        "china_provinces:\n  - Sichuan\n"
        "japan_prefectures:\n  - Kyoto\n"
        "cities:\n  - name: Sample Harbor\n    lat: 64.15\n    lon: -21.95\n"
    )
    planned_text = (
        visited_text
        + "planned_states:\n  - OR\n"
        + "planned:\n  - name: Sample Cove\n    lat: 44.0\n    lon: -120.5\n"
    )
    visited = render_maps(
        parse_config(visited_text, path="visited.yml"),
        tmp_path / "visited",
        "default",
        DAY,
        world=world,
        image_format="both",
        badge=True,
    )
    planned = render_maps(
        parse_config(planned_text, path="planned.yml"),
        tmp_path / "planned",
        "default",
        DAY,
        world=world,
        image_format="both",
        badge=True,
    )
    assert planned.resolved.planned_states == ("Oregon",)
    assert [city.name for city in planned.resolved.planned_cities] == ["Sample Cove"]
    assert planned.resolved.states == visited.resolved.states == ("Wyoming",)
    assert planned.resolved.countries == visited.resolved.countries
    assert planned.resolved.provinces == visited.resolved.provinces
    assert planned.resolved.prefectures == visited.resolved.prefectures
    assert "Sample Cove" not in {city.name for city in planned.resolved.cities}
    visited_stats = travel_stats(visited.resolved, world)
    planned_stats = travel_stats(planned.resolved, world)
    assert planned_stats == visited_stats
    assert planned_stats == TravelStats(
        countries=1,
        world_countries=world_country_total(world),
        us_states=1,
        china_provinces=1,
        japan_prefectures=1,
    )
    assert planned.badge_path.read_bytes() == visited.badge_path.read_bytes()
    badge = planned.badge_path.read_text(encoding="utf-8")
    assert "1 country" in badge
    assert "1 US state" in badge
    assert "2 US states" not in badge
    assert "1 China province" in badge
    assert "1 Japan prefecture" in badge
    assert "Oregon" not in badge
    assert "Sample Cove" not in badge
    planned_svg = planned.dark_svg_path.read_text(encoding="utf-8")
    visited_svg = visited.dark_svg_path.read_text(encoding="utf-8")
    assert 'id="planned-states"' in planned_svg
    assert 'id="planned-Sample-Cove"' in planned_svg
    assert "planned-states" not in visited_svg
    assert planned.dark_path.read_bytes() != visited.dark_path.read_bytes()


def test_whole_country_drops_provinces_and_counts_no_states(world, tmp_path: Path) -> None:
    result = render_maps(
        parse_config("countries:\n  - US\n  - CN\nus_states:\n  - WY\nchina_provinces:\n  - Sichuan\n"),
        tmp_path / "whole",
        "default",
        DAY,
        world=world,
        badge=True,
        image_format="svg",
    )
    text = result.badge_path.read_text(encoding="utf-8")
    assert "2 countries" in text
    assert "0 US states" in text
    assert "China" not in text
    assert "province" not in text
    assert result.resolved.states == ()
    assert result.resolved.provinces == ()


def test_cli_writes_the_badge_unless_disabled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "travel.yml"
    config.write_text("countries:\n  - NZ\n", encoding="utf-8")
    out = tmp_path / "dist"
    code = main(["--config", str(config), "--out", str(out)])
    assert code == 0
    captured = capsys.readouterr()
    assert str(out / "travel-badge.svg") in captured.out
    assert (out / "travel-map.png").is_file()
    assert (out / "travel-badge.svg").is_file()

    quiet = tmp_path / "quiet"
    code = main(["--config", str(config), "--out", str(quiet), "--badge", "false", "--format", "svg"])
    assert code == 0
    assert (quiet / "travel-map.svg").is_file()
    assert not (quiet / "travel-badge.svg").exists()
    assert "travel-badge.svg" not in capsys.readouterr().out


def test_unknown_badge_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "travel.yml"
    config.write_text("countries:\n  - NZ\n", encoding="utf-8")
    out = tmp_path / "dist"
    code = main(["--config", str(config), "--out", str(out), "--badge", "yes"])
    assert code == 1
    assert not out.exists()
    captured = capsys.readouterr()
    assert "yes" in captured.err
    assert "true" in captured.err
    assert "false" in captured.err


def test_badge_document_rejects_a_non_bool_flag(world, tmp_path: Path) -> None:
    config = parse_config("countries:\n  - NZ\n")
    with pytest.raises(InputError, match="badge"):
        render_maps(config, tmp_path / "dist", "default", DAY, world=world, badge="true")
    assert not (tmp_path / "dist").exists()


def test_readme_and_changelog_document_the_badge() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "demo/travel-badge.svg" in readme
    assert "--badge" in readme
    assert "badge: false" in readme or "`false`" in readme
    assert changelog.split("## [Unreleased]", 1)[1].split("## [", 1)[0].count("travel-badge.svg") >= 1
    assert "## [Unreleased]" in changelog


def test_example_badge_matches_the_sample_config(world, tmp_path: Path) -> None:
    from footprint import load_config, resolve_travel, travel_stats

    config = load_config(ROOT / "travel.example.yml")
    resolved = resolve_travel(config, world)
    stats = travel_stats(resolved, world)
    document = badge_document(stats, "default")
    assert resolved.planned_states == ("Oregon",)
    assert [city.name for city in resolved.planned_cities] == ["Sample Cove"]
    assert stats.us_states == len(resolved.states) == 2
    assert "3 countries" in document
    assert "2 US states" in document
    assert "3 US states" not in document
    assert "Oregon" not in document
    assert "Sample Cove" not in document
    assert "2 China provinces" in document
    assert "2 Japan prefectures" in document
    assert percent_of_world(3, stats.world_countries) in document
    assert stats.world_countries == 241
