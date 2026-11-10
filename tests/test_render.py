"""Name resolution, the Pacific shift, and a smoke render."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from footprint import (
    SEAM,
    City,
    ConfigError,
    DataError,
    TravelConfig,
    load_checksums,
    load_world,
    locate_dataset,
    parse_config,
    render_maps,
    resolve_token,
    resolve_travel,
    shift_geometry,
    suggest_names,
    verify_sha256,
)
from shapely.geometry import box


@pytest.fixture(scope="module")
def world():
    return load_world()


def test_shift_moves_the_americas_and_leaves_europe() -> None:
    europe = shift_geometry(box(10, 40, 20, 50))
    assert europe.bounds[0] == pytest.approx(10)

    alaska = shift_geometry(box(-150, 60, -140, 70))
    assert alaska.bounds[0] == pytest.approx(210)
    assert alaska.bounds[2] == pytest.approx(220)

    crossing = shift_geometry(box(-40, 0, -20, 10))
    assert crossing.bounds[0] == pytest.approx(SEAM)
    assert crossing.bounds[2] == pytest.approx(330)


def test_country_codes_and_names_resolve_to_one_id(world) -> None:
    index, names = world.country_index, world.country_names
    assert resolve_token("NZ", index, names, field="countries", example="example") == "NZL"
    assert resolve_token("NZL", index, names, field="countries", example="example") == "NZL"
    assert resolve_token("New Zealand", index, names, field="countries", example="example") == "NZL"
    assert resolve_token("uk", index, names, field="countries", example="example") == "GBR"
    assert resolve_token("NO", index, names, field="countries", example="example") == "NOR"
    assert resolve_token("FR", index, names, field="countries", example="example") == "FRA"
    assert resolve_token("France", index, names, field="countries", example="example") == "FRA"
    assert resolve_token("United States", index, names, field="countries", example="example") == "USA"


def test_same_country_under_two_labels_is_rejected(world) -> None:
    config = parse_config("countries:\n  - NZ\n  - 'New Zealand'\n")
    with pytest.raises(ConfigError, match="same country"):
        resolve_travel(config, world)


def test_unknown_country_suggests_a_close_name(world) -> None:
    config = parse_config("countries:\n  - Franc\n")
    with pytest.raises(ConfigError, match="France"):
        resolve_travel(config, world)


def test_korea_asks_which_one(world) -> None:
    config = parse_config("countries:\n  - Korea\n")
    with pytest.raises(ConfigError, match="North Korea") as caught:
        resolve_travel(config, world)
    assert "South Korea" in str(caught.value)


def test_unknown_place_without_a_neighbour_has_no_guess(world) -> None:
    config = parse_config("countries:\n  - Atlantis\n")
    with pytest.raises(ConfigError, match="Atlantis") as caught:
        resolve_travel(config, world)
    assert "Did you mean" not in str(caught.value)


def test_state_name_and_postal_code_match(world) -> None:
    config = parse_config("us_states:\n  - Wyoming\n  - CO\n")
    resolved = resolve_travel(config, world)
    assert resolved.states == ("Wyoming", "Colorado")
    assert resolved.countries == ()


def test_washington_state_is_not_hidden_by_the_district(world) -> None:
    config = parse_config("us_states:\n  - Washington\n  - DC\n")
    resolved = resolve_travel(config, world)
    assert resolved.states == ("Washington", "District of Columbia")


def test_state_listed_twice_is_rejected(world) -> None:
    config = parse_config("us_states:\n  - WY\n  - Wyoming\n")
    with pytest.raises(ConfigError, match="same state"):
        resolve_travel(config, world)


def test_unknown_state_is_rejected(world) -> None:
    config = parse_config("us_states:\n  - Notastate\n")
    with pytest.raises(ConfigError, match="Notastate"):
        resolve_travel(config, world)


def test_planned_places_are_not_visited(world) -> None:
    config = parse_config(
        "countries:\n  - NZ\n"
        "us_states:\n  - CO\n"
        "cities:\n  - name: Sample Harbor\n    lat: 64.15\n    lon: -21.95\n"
        "planned_states:\n  - OR\n"
        "planned:\n  - name: Sample Cove\n    lat: 44\n    lon: -120.5\n"
    )
    resolved = resolve_travel(config, world)
    assert resolved.countries == ("NZL",)
    assert resolved.states == ("Colorado",)
    assert [city.name for city in resolved.cities] == ["Sample Harbor"]
    assert resolved.planned_states == ("Oregon",)
    assert [city.name for city in resolved.planned_cities] == ["Sample Cove"]
    assert "Oregon" not in resolved.states
    assert "Sample Cove" not in {city.name for city in resolved.cities}


def test_planned_state_already_visited_is_rejected(world) -> None:
    config = parse_config("us_states:\n  - WY\nplanned_states:\n  - Wyoming\n")
    with pytest.raises(ConfigError, match="already listed under us_states"):
        resolve_travel(config, world)


def test_planned_state_rejected_when_whole_us_is_visited(world) -> None:
    config = parse_config("countries:\n  - US\nplanned_states:\n  - FL\n")
    with pytest.raises(ConfigError, match="'FL' cannot be planned because United States"):
        resolve_travel(config, world)


def test_listing_the_whole_country_covers_states(world) -> None:
    config = parse_config("countries:\n  - US\nus_states:\n  - WY\n")
    resolved = resolve_travel(config, world)
    assert resolved.countries == ("USA",)
    assert resolved.states == ()
    assert resolved.note is not None
    assert "us_states" in resolved.note


def test_china_and_japan_names_resolve(world) -> None:
    config = parse_config(
        "china_provinces:\n"
        "  - Zhejiang\n"
        "  - CN-SC\n"
        "  - Beijing\n"
        "  - 'Inner Mongolia'\n"
        "japan_prefectures:\n"
        "  - Kyoto\n"
        "  - Hokkaido\n"
        "  - JP-13\n"
        "  - Osaka\n"
    )
    resolved = resolve_travel(config, world)
    assert resolved.provinces == ("Zhejiang", "Sichuan", "Beijing", "Inner Mongol")
    assert resolved.prefectures == ("Kyōto", "Hokkaidō", "Tokyo", "Ōsaka")
    assert resolved.countries == ()
    assert len(world.province_names) == 31
    assert len(world.prefecture_names) == 47


def test_unknown_province_suggests_a_close_name(world) -> None:
    config = parse_config("china_provinces:\n  - Zhejiag\n")
    with pytest.raises(ConfigError, match="Zhejiang") as caught:
        resolve_travel(config, world)
    message = str(caught.value)
    assert "Zhejiag" in message
    assert "china_provinces" in message


def test_unknown_prefecture_names_the_entry(world) -> None:
    config = parse_config("japan_prefectures:\n  - Notaprefecture\n")
    with pytest.raises(ConfigError, match="Notaprefecture") as caught:
        resolve_travel(config, world)
    assert "japan_prefectures" in str(caught.value)
    assert "Did you mean" not in str(caught.value)


def test_province_listed_twice_is_rejected(world) -> None:
    config = parse_config("china_provinces:\n  - Zhejiang\n  - CN-ZJ\n")
    with pytest.raises(ConfigError, match="same province"):
        resolve_travel(config, world)


def test_prefecture_listed_twice_is_rejected(world) -> None:
    config = parse_config("japan_prefectures:\n  - Kyoto\n  - JP-26\n")
    with pytest.raises(ConfigError, match="same prefecture"):
        resolve_travel(config, world)


def test_listing_china_or_japan_covers_subdivisions(world) -> None:
    config = parse_config(
        "countries:\n  - CN\n  - Japan\n"
        "china_provinces:\n  - Zhejiang\n"
        "japan_prefectures:\n  - Kyoto\n"
    )
    resolved = resolve_travel(config, world)
    assert resolved.countries == ("CHN", "JPN")
    assert resolved.provinces == ()
    assert resolved.prefectures == ()
    assert resolved.note is not None
    assert "china_provinces" in resolved.note
    assert "japan_prefectures" in resolved.note


def test_ambiguous_token_is_rejected() -> None:
    index = {"georgia": None}
    with pytest.raises(ConfigError, match="more than one"):
        resolve_token("Georgia", index, ["Georgia"], field="countries", example="Use a code.")


def test_suggestions_prefer_whole_words() -> None:
    names = ["North Korea", "South Korea", "France", "New Zealand"]
    assert suggest_names("Korea", names) == ["North Korea", "South Korea"]
    assert suggest_names("Franc", names) == ["France"]
    assert suggest_names("Atlantis", names) == []


def _png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert data[12:16] == b"IHDR"
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    return width, height


def _count_near(path: Path, hex_color: str, tolerance: int = 36) -> int:
    import matplotlib.image as mpimg

    image = mpimg.imread(path)
    red, green, blue = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    hits = 0
    for row in image:
        for pixel in row:
            distance = (
                abs(pixel[0] * 255 - red)
                + abs(pixel[1] * 255 - green)
                + abs(pixel[2] * 255 - blue)
            )
            if distance <= tolerance:
                hits += 1
    return hits


def test_planned_png_is_static_and_not_a_solid_visited_fill(world, tmp_path: Path) -> None:
    planned_text = (
        "planned_states:\n  - TX\n"
        "planned:\n  - name: Sample Cove\n    lat: 31.0\n    lon: -99.0\n"
    )
    planned = render_maps(
        parse_config(planned_text),
        tmp_path / "planned",
        "default",
        date(2026, 6, 1),
        world=world,
        image_format="png",
    )
    visited = render_maps(
        parse_config("us_states:\n  - TX\n"),
        tmp_path / "visited",
        "default",
        date(2026, 6, 1),
        world=world,
    )
    assert planned.dark_svg_path is None
    assert planned.resolved.states == ()
    assert planned.resolved.cities == ()
    assert planned.resolved.countries == ()
    assert planned.resolved.planned_states == ("Texas",)
    assert [city.name for city in planned.resolved.planned_cities] == ["Sample Cove"]
    assert planned.dark_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert not (tmp_path / "planned" / "travel-map.svg").exists()
    planned_green = _count_near(planned.dark_path, "#3fb950")
    visited_green = _count_near(visited.dark_path, "#3fb950")
    # The dashed outline and the dot are accent-colored. The fill is 40%
    # opacity, so it does not count as a solid visited shape.
    assert planned_green > 10
    assert visited_green > planned_green * 4


def test_smoke_render_paints_a_country_and_one_state(world, tmp_path: Path) -> None:
    text = (
        "countries:\n  - BR\n"
        "us_states:\n  - WY\n"
        "cities:\n  - name: Site A\n    lat: -15.0\n    lon: -47.0\n"
    )
    config = parse_config(text, path="smoke.yml")
    result = render_maps(config, tmp_path / "dist", "default", date(2026, 6, 1), world=world)
    for path in (result.dark_path, result.light_path):
        assert path.is_file()
        assert path.stat().st_size > 8_000
        width, height = _png_size(path)
        assert width == 1200
        assert height in {474, 475}
    assert result.dark_path.name == "travel-map.png"
    assert result.light_path.name == "travel-map-light.png"
    assert result.dark_svg_path is None
    assert result.light_svg_path is None
    assert not (tmp_path / "dist" / "travel-map.svg").exists()
    assert _count_near(result.dark_path, "#0d1117") > 50_000
    assert _count_near(result.light_path, "#ffffff") > 50_000
    assert _count_near(result.dark_path, "#3fb950") > 1_000
    assert result.resolved.states == ("Wyoming",)
    assert result.palette == "default"
    assert result.resolved.cities == (City("Site A", -15.0, -47.0),)


def test_christmas_palette_changes_the_visited_color(world, tmp_path: Path) -> None:
    config = TravelConfig(countries=("BR",), us_states=(), cities=())
    dark_dir = tmp_path / "dark"
    festive_dir = tmp_path / "festive"
    plain = render_maps(config, dark_dir, "default", date(2026, 6, 1), world=world)
    festive = render_maps(config, festive_dir, "auto", date(2026, 12, 25), world=world)
    assert festive.palette == "christmas"
    assert plain.dark_path.read_bytes() != festive.dark_path.read_bytes()
    red = _count_near(festive.dark_path, "#bc4749")
    green = _count_near(festive.dark_path, "#6a994e")
    assert red > 400
    assert green > 400
    # The bands split the visited shape about evenly.
    assert 0.25 < green / (red + green) < 0.75
    assert _count_near(festive.dark_path, "#3fb950") < 50
    assert _count_near(festive.light_path, "#ffffff") > 50_000
    assert _count_near(festive.light_path, "#bc4749") > 400
    assert _count_near(festive.light_path, "#6a994e") > 400
    assert _count_near(plain.dark_path, "#6a994e") < 40


def test_us_states_do_not_fill_the_whole_country(world, tmp_path: Path) -> None:
    partial = render_maps(
        parse_config("us_states:\n  - WY\n"),
        tmp_path / "partial",
        "default",
        date(2026, 6, 1),
        world=world,
    )
    whole = render_maps(
        parse_config("countries:\n  - US\n"),
        tmp_path / "whole",
        "default",
        date(2026, 6, 1),
        world=world,
    )
    state_green = _count_near(partial.dark_path, "#3fb950")
    country_green = _count_near(whole.dark_path, "#3fb950")
    assert partial.resolved.states == ("Wyoming",)
    assert partial.resolved.countries == ()
    assert state_green > 30
    assert country_green > state_green * 8


def test_subdivisions_do_not_fill_the_whole_country(world, tmp_path: Path) -> None:
    partial = render_maps(
        parse_config(
            "china_provinces:\n  - Sichuan\n"
            "japan_prefectures:\n  - Hokkaido\n"
        ),
        tmp_path / "partial",
        "default",
        date(2026, 6, 1),
        world=world,
    )
    whole = render_maps(
        parse_config("countries:\n  - CN\n  - JP\n"),
        tmp_path / "whole",
        "default",
        date(2026, 6, 1),
        world=world,
    )
    partial_green = _count_near(partial.dark_path, "#3fb950")
    whole_green = _count_near(whole.dark_path, "#3fb950")
    assert partial.resolved.provinces == ("Sichuan",)
    assert partial.resolved.prefectures == ("Hokkaidō",)
    assert partial.resolved.countries == ()
    assert partial_green > 100
    assert whole_green > partial_green * 3
    # Default is a solid fill, so the Christmas stripe green is absent.
    assert _count_near(partial.dark_path, "#6a994e") < 40
    assert _count_near(partial.light_path, "#1a7f37") > 100


def test_christmas_stripes_cover_a_province(world, tmp_path: Path) -> None:
    festive = render_maps(
        parse_config("china_provinces:\n  - Sichuan\njapan_prefectures:\n  - Hokkaido\n"),
        tmp_path / "festive",
        "christmas",
        date(2026, 12, 25),
        world=world,
    )
    assert festive.palette == "christmas"
    red = _count_near(festive.dark_path, "#bc4749")
    green = _count_near(festive.dark_path, "#6a994e")
    assert red > 100
    assert green > 100
    assert 0.25 < green / (red + green) < 0.75
    assert _count_near(festive.light_path, "#bc4749") > 100
    assert _count_near(festive.light_path, "#6a994e") > 100
    assert _count_near(festive.dark_path, "#3fb950") < 50


def test_vendored_zips_match_checksums() -> None:
    from footprint import DATASET_NAMES, VENDOR_DIR

    sums = load_checksums()
    for name in DATASET_NAMES:
        path = locate_dataset(name)
        assert path == VENDOR_DIR / name
        verify_sha256(path, sums[name], name)


def test_download_cache_is_used_on_the_second_call(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(url: str, dest: Path) -> None:
        calls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"PK\x03\x04not-a-real-zip")

    vendor = tmp_path / "vendor"
    vendor.mkdir()
    cache = tmp_path / "cache"
    name = "ne_50m_admin_0_countries.zip"
    first = locate_dataset(name, vendor_dir=vendor, cache_dir=cache, fetch=fetch, verify=False)
    second = locate_dataset(name, vendor_dir=vendor, cache_dir=cache, fetch=fetch, verify=False)
    assert first == second
    assert calls == [
        "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip"
    ]


def test_vendor_file_skips_the_download(tmp_path: Path) -> None:
    vendor = tmp_path / "vendor"
    vendor.mkdir()
    name = "ne_50m_admin_0_countries.zip"
    (vendor / name).write_bytes(b"PK\x03\x04vendored")

    def fetch(url: str, dest: Path) -> None:
        raise AssertionError("vendored file should not be downloaded")

    found = locate_dataset(
        name,
        vendor_dir=vendor,
        cache_dir=tmp_path / "cache",
        fetch=fetch,
        verify=False,
    )
    assert found == vendor / name


def test_bad_checksum_is_rejected(tmp_path: Path) -> None:
    payload = tmp_path / "map.zip"
    payload.write_bytes(b"not the natural earth zip")
    with pytest.raises(DataError, match="sha256"):
        verify_sha256(payload, "ab" * 32, "ne_50m_admin_0_countries.zip")
