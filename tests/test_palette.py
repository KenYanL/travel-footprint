"""Palette names and the UTC holiday switch shared with contrib-tetris."""

from __future__ import annotations

from datetime import date

import pytest

from footprint import PALETTES, THEMES, InputError, parse_palette, resolve_palette


def test_palette_strips_and_lowercases() -> None:
    assert parse_palette(" Halloween ") == "halloween"
    assert parse_palette("Christmas") == "christmas"
    assert parse_palette("NewYear") == "newyear"
    assert parse_palette("AUTO") == "auto"
    assert parse_palette("default") == "default"


def test_unknown_palette_names_the_choices() -> None:
    with pytest.raises(InputError, match="neon") as caught:
        parse_palette("neon")
    message = str(caught.value)
    assert "halloween" in message
    assert "christmas" in message
    assert "newyear" in message
    assert "auto" in message


def test_empty_palette_is_rejected() -> None:
    with pytest.raises(InputError, match="empty"):
        parse_palette("  ")
    with pytest.raises(InputError, match="palette"):
        parse_palette(None)


def test_auto_is_halloween_only_on_october_31() -> None:
    for year in (2024, 2026, 2028):
        assert resolve_palette("auto", date(year, 10, 31)) == "halloween"
        assert resolve_palette("auto", date(year, 10, 30)) == "default"
        assert resolve_palette("auto", date(year, 11, 1)) == "default"
    assert resolve_palette("halloween", date(2026, 11, 1)) == "halloween"
    assert resolve_palette("halloween", date(2026, 12, 25)) == "halloween"


def test_auto_is_christmas_on_december_24_through_26() -> None:
    for year in (2024, 2026, 2028):
        for day in (24, 25, 26):
            assert resolve_palette("auto", date(year, 12, day)) == "christmas"
        assert resolve_palette("auto", date(year, 12, 23)) == "default"
        assert resolve_palette("auto", date(year, 12, 27)) == "default"
        assert resolve_palette("auto", date(year, 10, 31)) == "halloween"
    assert resolve_palette("christmas", date(2026, 12, 23)) == "christmas"
    assert resolve_palette("christmas", date(2026, 6, 1)) == "christmas"


def test_auto_is_newyear_on_january_1() -> None:
    for year in (2024, 2026, 2028):
        assert resolve_palette("auto", date(year, 1, 1)) == "newyear"
        assert resolve_palette("auto", date(year, 12, 31)) == "default"
        assert resolve_palette("auto", date(year, 1, 2)) == "default"
        assert resolve_palette("auto", date(year, 10, 31)) == "halloween"
    assert resolve_palette("newyear", date(2026, 6, 1)) == "newyear"
    assert resolve_palette("newyear", date(2026, 12, 25)) == "newyear"


def test_dark_palette_values_match_the_contract() -> None:
    assert PALETTES["default"]["dark"] == {"visited": "#3fb950", "dot": "#ffffff"}
    assert PALETTES["halloween"]["dark"] == {"visited": "#c46212", "dot": "#e3d04f"}
    assert PALETTES["christmas"]["dark"] == {
        "visited": "#bc4749",
        "stripe": "#6a994e",
        "dot": "#f2e8cf",
    }
    assert PALETTES["newyear"]["dark"] == {
        "visited": "#cc6f00",
        "stripe": "#4d2a00",
        "dot": "#f9e6a8",
    }
    assert "stripe" not in PALETTES["default"]["dark"]
    assert "stripe" not in PALETTES["halloween"]["dark"]


def test_light_palette_values_are_the_documented_equivalents() -> None:
    assert PALETTES["default"]["light"] == {"visited": "#1a7f37", "dot": "#1f2328"}
    assert PALETTES["halloween"]["light"] == {"visited": "#c46212", "dot": "#1f2328"}
    assert PALETTES["christmas"]["light"] == {
        "visited": "#bc4749",
        "stripe": "#6a994e",
        "dot": "#f2e8cf",
    }
    assert PALETTES["newyear"]["light"] == {
        "visited": "#cc6f00",
        "stripe": "#4d2a00",
        "dot": "#f9e6a8",
    }


def test_chrome_colors() -> None:
    assert THEMES["dark"]["background"] == "#0d1117"
    assert THEMES["dark"]["land"] == "#30363d"
    assert THEMES["dark"]["edge"] == "#0d1117"
    assert THEMES["light"]["background"] == "#ffffff"
    assert THEMES["light"]["land"] == "#d0d7de"
