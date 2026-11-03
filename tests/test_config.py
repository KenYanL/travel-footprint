"""Structural checks for the travel YAML file. These do not read the map."""

from __future__ import annotations

from pathlib import Path

import pytest

from footprint import ConfigError, load_config, parse_config

EXAMPLE = Path(__file__).resolve().parents[1] / "travel.example.yml"


def test_example_file_has_the_documented_shape() -> None:
    config = load_config(EXAMPLE)
    assert config.countries == ("IS", "NZ", "CL")
    assert config.us_states == ("CO", "ME")
    assert config.china_provinces == ("Zhejiang", "Sichuan")
    assert config.japan_prefectures == ("Kyoto", "Hokkaido")
    assert [city.name for city in config.cities] == ["Sample Harbor", "Sample Ridge"]
    assert config.cities[0].lat == pytest.approx(64.15)
    assert config.cities[0].lon == pytest.approx(-21.95)


def test_omitted_keys_are_empty_lists() -> None:
    config = parse_config("countries:\n  - NZ\n")
    assert config.countries == ("NZ",)
    assert config.us_states == ()
    assert config.china_provinces == ()
    assert config.japan_prefectures == ()
    assert config.cities == ()


def test_empty_lists_are_allowed() -> None:
    config = parse_config("countries: []\nus_states: []\ncities: []\n")
    assert config.countries == ()
    assert config.cities == ()


def test_empty_document_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="empty"):
        parse_config("")
    with pytest.raises(ConfigError, match="empty"):
        parse_config("# nothing here\n")


def test_root_must_be_a_mapping() -> None:
    with pytest.raises(ConfigError, match="mapping"):
        parse_config("- NZ\n")


def test_unknown_key_names_the_supported_ones() -> None:
    with pytest.raises(ConfigError, match="provinces") as caught:
        parse_config("provinces:\n  - Somewhere\n")
    message = str(caught.value)
    assert "countries" in message
    assert "not supported yet" in message


def test_explicit_null_is_rejected() -> None:
    with pytest.raises(ConfigError, match="countries is null"):
        parse_config("countries:\n")


def test_countries_must_be_a_list() -> None:
    with pytest.raises(ConfigError, match="not a list"):
        parse_config("countries: NZ\n")


def test_non_text_country_is_rejected() -> None:
    with pytest.raises(ConfigError, match="entry 1"):
        parse_config("countries:\n  - 64\n")


def test_empty_country_is_rejected() -> None:
    with pytest.raises(ConfigError, match="empty"):
        parse_config("countries:\n  - '  '\n")


def test_repeated_country_text_is_rejected() -> None:
    with pytest.raises(ConfigError, match="repeats"):
        parse_config("countries:\n  - nz\n  - NZ\n")


def test_norway_code_is_not_read_as_a_boolean() -> None:
    config = parse_config("countries:\n  - NO\n")
    assert config.countries == ("NO",)


def test_repeated_yaml_key_is_rejected() -> None:
    text = "countries:\n  - NZ\ncountries:\n  - CL\n"
    with pytest.raises(ConfigError, match="repeated"):
        parse_config(text)


def test_broken_yaml_names_the_file() -> None:
    with pytest.raises(ConfigError, match="not valid YAML"):
        parse_config("countries: [\n", path="travel.yml")


def test_missing_file_names_the_path(tmp_path: Path) -> None:
    missing = tmp_path / "travel.yml"
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(missing)


def test_city_requires_coordinates() -> None:
    text = "cities:\n  - name: Sample Harbor\n"
    with pytest.raises(ConfigError, match="lat is missing"):
        parse_config(text)


def test_latitude_and_longitude_aliases_work() -> None:
    text = "cities:\n  - name: Sample Harbor\n    latitude: 10\n    longitude: -20\n"
    config = parse_config(text)
    assert config.cities[0].lat == 10
    assert config.cities[0].lon == -20


def test_numeric_strings_are_accepted() -> None:
    text = "cities:\n  - name: Sample Harbor\n    lat: '64.15'\n    lon: '-21.95'\n"
    config = parse_config(text)
    assert config.cities[0].lat == pytest.approx(64.15)


def test_lat_and_latitude_together_are_rejected() -> None:
    text = "cities:\n  - name: Sample Harbor\n    lat: 1\n    latitude: 2\n    lon: 3\n"
    with pytest.raises(ConfigError, match="both lat and latitude"):
        parse_config(text)


def test_latitude_out_of_range() -> None:
    text = "cities:\n  - name: Sample Harbor\n    lat: 91\n    lon: 0\n"
    with pytest.raises(ConfigError, match="outside -90 to 90"):
        parse_config(text)


def test_longitude_out_of_range() -> None:
    text = "cities:\n  - name: Sample Harbor\n    lat: 0\n    lon: -181\n"
    with pytest.raises(ConfigError, match="outside -180 to 180"):
        parse_config(text)


def test_non_finite_coordinate_is_rejected() -> None:
    text = "cities:\n  - name: Sample Harbor\n    lat: .nan\n    lon: 0\n"
    with pytest.raises(ConfigError, match="not a finite number"):
        parse_config(text)


def test_city_must_be_a_mapping() -> None:
    with pytest.raises(ConfigError, match="not a mapping"):
        parse_config("cities:\n  - Sample Harbor\n")


def test_unknown_city_key_is_rejected() -> None:
    text = "cities:\n  - name: Sample Harbor\n    lat: 1\n    lon: 2\n    note: no\n"
    with pytest.raises(ConfigError, match="note"):
        parse_config(text)


def test_empty_city_name_is_rejected() -> None:
    text = "cities:\n  - name: '  '\n    lat: 1\n    lon: 2\n"
    with pytest.raises(ConfigError, match="non-empty"):
        parse_config(text)


def test_state_list_must_be_text() -> None:
    with pytest.raises(ConfigError, match="us_states"):
        parse_config("us_states:\n  - 12\n")


def test_province_and_prefecture_lists_must_be_text() -> None:
    with pytest.raises(ConfigError, match="china_provinces"):
        parse_config("china_provinces:\n  - 12\n")
    with pytest.raises(ConfigError, match="japan_prefectures"):
        parse_config("japan_prefectures: Kyoto\n")


def test_edges_of_the_coordinate_range_are_kept() -> None:
    text = "cities:\n  - name: Corner\n    lat: 90\n    lon: -180\n"
    config = parse_config(text)
    assert config.cities[0].lat == 90
    assert config.cities[0].lon == -180
