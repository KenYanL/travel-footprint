"""SVG maps: valid XML, the same projection and palette, and Christmas stripes."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

import pytest
from shapely.geometry import Point, Polygon

from footprint import (
    SVG_HEIGHT,
    SVG_WIDTH,
    STRIPE_FRACTION,
    STRIPE_PERIOD,
    THEMES,
    InputError,
    parse_config,
    parse_format,
    render_maps,
)

NS = "{http://www.w3.org/2000/svg}"
DAY = date(2026, 6, 1)

# Pacific-centred plate carrée, the same frame as the 1200×474 PNG.
SEAM = -30.0
NORTH = 84.0
SOUTH = -58.0


def _geo_to_svg(lon: float, lat: float) -> tuple[float, float]:
    shifted = lon + 360.0 if lon < SEAM else lon
    x = (shifted - SEAM) / 360.0 * 1200.0
    y = (NORTH - lat) / (NORTH - SOUTH) * 474.0
    return x, y


def _parse(path: Path) -> tuple[str, ET.Element]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<?xml")
    root = ET.fromstring(text)
    assert root.tag == f"{NS}svg"
    return text, root


def _by_id(root: ET.Element) -> dict[str, ET.Element]:
    return {element.get("id"): element for element in root.iter() if element.get("id")}


def _layers(root: ET.Element) -> set[str]:
    return {element.get("data-layer") for element in root.iter() if element.get("data-layer")}


def _path_bbox(data: str) -> tuple[float, float, float, float]:
    numbers = [float(token) for token in re.findall(r"-?\d+(?:\.\d+)?", data)]
    xs = numbers[0::2]
    ys = numbers[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _render(world, directory: Path, text: str, palette: str = "default"):
    config = parse_config(text, path="svg.yml")
    return render_maps(config, directory, palette, DAY, world=world, image_format="svg")


@pytest.fixture(scope="module")
def world():
    from footprint import load_world

    return load_world()


def test_format_names() -> None:
    assert parse_format("png") == "png"
    assert parse_format(" SVG ") == "svg"
    assert parse_format("Both") == "both"
    with pytest.raises(InputError, match="empty"):
        parse_format("  ")
    with pytest.raises(InputError, match="format") as caught:
        parse_format(None)
    assert "svg" in str(caught.value)
    assert "both" in str(caught.value)
    with pytest.raises(InputError, match="gif"):
        parse_format("gif")


def test_svg_frame_matches_the_png_pixel_grid() -> None:
    assert SVG_WIDTH == 1200
    assert SVG_HEIGHT == 474
    assert NORTH - SOUTH == 142


@pytest.mark.parametrize(
    ("palette", "theme", "visited", "dot", "stripe"),
    [
        ("default", "dark", "#3fb950", "#ffffff", None),
        ("default", "light", "#1a7f37", "#1f2328", None),
        ("halloween", "dark", "#c46212", "#e3d04f", None),
        ("halloween", "light", "#c46212", "#1f2328", None),
        ("christmas", "dark", "#bc4749", "#f2e8cf", "#6a994e"),
        ("christmas", "light", "#bc4749", "#f2e8cf", "#6a994e"),
    ],
)
def test_svg_colors_projection_and_stripes(world, tmp_path: Path, palette, theme, visited, dot, stripe) -> None:
    text = (
        "countries:\n  - NZ\n  - BR\n"
        "cities:\n"
        "  - name: Site A\n    lat: -15.0\n    lon: -47.0\n"
        "  - name: Site B\n    lat: -41.0\n    lon: 174.0\n"
    )
    result = _render(world, tmp_path / f"{palette}-{theme}", text, palette)
    paths = {"dark": result.dark_svg_path, "light": result.light_svg_path}
    assert result.dark_path is None
    assert result.light_path is None
    raw, root = _parse(paths[theme])
    assert root.get("width") == "1200"
    assert root.get("height") == "474"
    assert root.get("viewBox") == "0 0 1200 474"
    assert f"{NS}image" not in {element.tag for element in root.iter()}
    assert "<image" not in raw

    found = _by_id(root)
    chrome = THEMES[theme]
    assert found["background"].get("fill") == chrome["background"]
    assert found["land"].get("fill") == chrome["land"]
    assert found["visited"].get("fill") == visited
    assert _layers(root) == {"countries"}

    circles = [element for element in root.iter(f"{NS}circle")]
    assert len(circles) == 4
    expected = (_geo_to_svg(-47.0, -15.0), _geo_to_svg(174.0, -41.0))
    assert expected[0][0] > expected[1][0]
    for index, (cx, cy) in enumerate(expected):
        halo, mark = circles[index * 2], circles[index * 2 + 1]
        assert float(halo.get("cx")) == pytest.approx(cx, abs=0.02)
        assert float(halo.get("cy")) == pytest.approx(cy, abs=0.02)
        assert halo.get("cx") == mark.get("cx")
        assert halo.get("cy") == mark.get("cy")
        assert float(halo.get("r")) > float(mark.get("r"))
        assert halo.get("fill") == visited
        assert halo.get("fill-opacity") == "0.25"
        assert mark.get("fill") == dot
        assert mark.get("stroke") == visited

    pattern = found.get("christmas-stripes")
    if stripe is None:
        assert pattern is None
        assert "clipPath" not in {element.tag.removeprefix(NS) for element in root.iter()}
        assert "#6a994e" not in raw
        assert "#bc4749" not in raw
        assert "<pattern" not in raw
        return

    assert pattern is not None
    assert pattern.get("width") == str(STRIPE_PERIOD) == "8"
    assert pattern.get("height") == "8"
    assert pattern.get("patternUnits") == "userSpaceOnUse"
    assert found["stripes"].get("clip-path") == "url(#visited-clip)"
    rect = next(element for element in found["stripes"] if element.tag == f"{NS}rect")
    assert rect.get("fill") == "url(#christmas-stripes)"
    clip = next(element for element in found["visited-clip"] if element.tag == f"{NS}path")
    assert clip.get("clip-rule") == "evenodd"
    visited_paths = [element.get("d") for element in found["visited"] if element.get("d")]
    assert clip.get("d") == " ".join(visited_paths)
    assert_stripe_tile(pattern, stripe)
    assert visited in raw
    assert dot in raw


def assert_stripe_tile(pattern: ET.Element, stripe: str) -> None:
    polygons = []
    for element in pattern:
        if element.tag != f"{NS}polygon":
            continue
        assert element.get("fill") == stripe
        coords = [tuple(float(part) for part in pair.split(",")) for pair in element.get("points").split()]
        polygons.append(Polygon(coords))
    assert len(polygons) == 2
    period = STRIPE_PERIOD
    band = period * STRIPE_FRACTION
    step = 0.5
    for iy in range(int(period / step)):
        for ix in range(int(period / step)):
            x = (ix + 0.5) * step
            y = (iy + 0.5) * step
            remainder = (x + y) % period
            if abs(remainder - band) < 1e-6:
                continue
            inside = any(polygon.covers(Point(x, y)) for polygon in polygons)
            assert inside is (remainder < band)


def test_subdivisions_fill_on_their_own_and_a_country_fills_entirely(world, tmp_path: Path) -> None:
    partial = _render(
        world,
        tmp_path / "partial",
        "us_states:\n  - WY\nchina_provinces:\n  - Sichuan\njapan_prefectures:\n  - Hokkaido\n",
    )
    whole = _render(
        world,
        tmp_path / "whole",
        "countries:\n  - US\n  - CN\n  - JP\n"
        "us_states:\n  - WY\n"
        "china_provinces:\n  - Sichuan\n"
        "japan_prefectures:\n  - Hokkaido\n",
    )
    _, partial_root = _parse(partial.dark_svg_path)
    _, whole_root = _parse(whole.dark_svg_path)
    assert _layers(partial_root) == {"states", "provinces", "prefectures"}
    assert _layers(whole_root) == {"countries"}
    assert partial.resolved.countries == ()
    assert whole.resolved.states == ()
    assert whole.resolved.provinces == ()
    assert whole.resolved.prefectures == ()

    partial_paths = {
        element.get("data-layer"): element.get("d")
        for element in partial_root.iter()
        if element.get("data-layer")
    }
    whole_path = next(
        element.get("d") for element in whole_root.iter() if element.get("data-layer") == "countries"
    )
    partial_area = 0.0
    for layer, column, key in (
        ("states", "name", "Wyoming"),
        ("provinces", "name", "Sichuan"),
        ("prefectures", "name", "Hokkaidō"),
    ):
        frame = {"states": world.states, "provinces": world.provinces, "prefectures": world.prefectures}[layer]
        geom = frame[frame[column] == key].geometry.iloc[0]
        minx, miny, maxx, maxy = geom.bounds
        left, top = _geo_to_svg(minx, maxy)
        right, bottom = _geo_to_svg(maxx, miny)
        path_left, path_top, path_right, path_bottom = _path_bbox(partial_paths[layer])
        assert path_left == pytest.approx(left, abs=0.05)
        assert path_top == pytest.approx(top, abs=0.05)
        assert path_right == pytest.approx(right, abs=0.05)
        assert path_bottom == pytest.approx(bottom, abs=0.05)
        partial_area += (path_right - path_left) * (path_bottom - path_top)

    whole_box = _path_bbox(whole_path)
    whole_area = (whole_box[2] - whole_box[0]) * (whole_box[3] - whole_box[1])
    assert whole_area > partial_area * 3
    # The basemap is still the plain land color; only the listed shapes are visited.
    assert _by_id(partial_root)["land"].get("fill") == "#30363d"
    assert _by_id(partial_root)["visited"].get("fill") == "#3fb950"


def test_png_bytes_stay_the_same_when_svg_is_added(world, tmp_path: Path) -> None:
    config = parse_config("countries:\n  - NZ\n", path="nz.yml")
    png = render_maps(config, tmp_path / "png", "default", DAY, world=world)
    both = render_maps(config, tmp_path / "both", "default", DAY, world=world, image_format="both")
    assert png.dark_svg_path is None
    assert both.dark_path.read_bytes() == png.dark_path.read_bytes()
    assert both.light_path.read_bytes() == png.light_path.read_bytes()
    assert both.dark_svg_path.is_file()
    assert both.light_svg_path.is_file()


def test_empty_config_is_land_without_visited_shapes(world, tmp_path: Path) -> None:
    result = _render(world, tmp_path / "empty", "{}\n")
    _, root = _parse(result.dark_svg_path)
    assert _layers(root) == set()
    assert "visited" not in _by_id(root)
    assert _by_id(root)["land"].get("fill") == "#30363d"
    assert list(root.iter(f"{NS}circle")) == []
