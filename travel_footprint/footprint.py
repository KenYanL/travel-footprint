"""Load a travel file and draw a Pacific-centred world map.

Countries, US states, Chinese provinces, Japanese prefectures, and cities come
from the caller's YAML file. ``planned`` cities and ``planned_states`` are
drawn too, and they are not counted as visited. Coastlines come from the
Natural Earth extracts in ``data/`` next to this module (see ``data/README.md``).
The map is plate carrée, seam at 30°W, so the Pacific sits in the middle and
the Americas sit on the right. The default files are PNG. The same map can also be written
as SVG. Planned places pulse only in the SVG. A stats badge SVG is written
next to those files unless the caller turns it off. Planned places stay out
of the badge counts.
"""

from __future__ import annotations

import difflib
import hashlib
import math
import os
import re
import tempfile
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.colors import to_rgb
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from shapely.affinity import translate
from shapely.geometry import box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent
VENDOR_DIR = ROOT / "data"

COUNTRIES_ZIP = "ne_50m_admin_0_countries.zip"
STATES_ZIP = "ne_50m_admin_1_states_provinces.zip"
# Natural Earth 50m admin-1 has China and the United States, and not Japan.
# Prefectures are a Japan-only extract of the public-domain 10m admin-1 theme.
JAPAN_ZIP = "ne_10m_admin_1_japan_prefectures.zip"
DATASET_NAMES = (COUNTRIES_ZIP, STATES_ZIP, JAPAN_ZIP)
DATASET_URLS = {
    COUNTRIES_ZIP: "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip",
    STATES_ZIP: "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_1_states_provinces.zip",
}

DARK_FILENAME = "travel-map.png"
LIGHT_FILENAME = "travel-map-light.png"
DARK_SVG_FILENAME = "travel-map.svg"
LIGHT_SVG_FILENAME = "travel-map-light.svg"
BADGE_FILENAME = "travel-badge.svg"

# Pacific-centred plate carrée. Seam at 30°W (central meridian 150°E).
# Land west of the seam is shifted by +360 so the Americas sit on the right.
SEAM = -30.0
MAP_XLIM = (SEAM, SEAM + 360.0)
MAP_YLIM = (-58.0, 84.0)
_WEST = box(-180.0, -90.0, SEAM, 90.0)
_EAST = box(SEAM, -90.0, 180.0, 90.0)

# Figure size matches a 360° by 142° frame, so the map fills the PNG.
# SVG user units use that same pixel grid (1200 by 474).
FIGSIZE = (12.0, 4.74)
FIG_DPI = 100
SVG_WIDTH = int(round(FIGSIZE[0] * FIG_DPI))
SVG_HEIGHT = int(round(FIGSIZE[1] * FIG_DPI))

# Matplotlib point sizes shared by the PNG and the SVG so the two files match.
LAND_LINEWIDTH = 0.3
SUBDIVISION_LINEWIDTH = 0.18
COUNTRY_LINEWIDTH = 0.3
CITY_HALO_AREA = 35
CITY_DOT_AREA = 10
CITY_DOT_LINEWIDTH = 0.8
CITY_HALO_ALPHA = 0.25

# Planned places use the palette accent. The PNG is a static fill and dot.
# The SVG pulses the same shapes with SMIL; viewers that ignore animation
# still show the base opacity, the dashed outline, and the solid dot.
PLANNED_FILL_ALPHA = 0.4
PLANNED_OPACITY_VALUES = "0.25;0.6;0.25"
PLANNED_DURATION = "1.8s"
PLANNED_EDGE_WIDTH = 0.6  # points, matching the dashed outline on the PNG
PLANNED_DASH_ON = 2.0  # points
PLANNED_DASH_OFF = 1.5  # points
PLANNED_RING_RADIUS = 2.5
PLANNED_RING_RADIUS_END = 9
PLANNED_RING_STROKE = 1.2
PLANNED_DOT_RADIUS = 2.6
PLANNED_RING_OPACITY = "1;0"
PLANNED_DOT_OPACITY = "1;.45;1"

# Dark chrome matches the GitHub dark canvas: grey land, no visible border.
THEMES: dict[str, dict[str, str]] = {
    "dark": {
        "background": "#0d1117",
        "land": "#30363d",
        "edge": "#0d1117",
    },
    "light": {
        "background": "#ffffff",
        "land": "#d0d7de",
        "edge": "#ffffff",
    },
}

# ``visited`` fills a whole country, or a listed subdivision and nothing else.
# ``stripe``, when set, is painted as diagonal bands over that fill.
# ``dot`` is the city marker. Light dots are darker where a light color would
# disappear on white; Christmas keeps the cream dot on both themes because the
# dot sits on the red and green bands.
PALETTES: dict[str, dict[str, dict[str, str]]] = {
    "default": {
        "dark": {"visited": "#3fb950", "dot": "#ffffff"},
        "light": {"visited": "#1a7f37", "dot": "#1f2328"},
    },
    "halloween": {
        # Orange and yellow from GitHub Primer @primer/primitives 11.10.0,
        # dark --contribution-halloween-bgColor. The light map keeps the same
        # orange fill and uses a dark dot so it stays visible on white.
        "dark": {"visited": "#c46212", "dot": "#e3d04f"},
        "light": {"visited": "#c46212", "dot": "#1f2328"},
    },
    "christmas": {
        # Coolors' most popular Christmas palette
        # https://coolors.co/palettes/popular/christmas
        # 386641, 6a994e, a7c957, f2e8cf, bc4749.
        # Visited shapes are red with green diagonal stripes, not a solid fill.
        "dark": {"visited": "#bc4749", "stripe": "#6a994e", "dot": "#f2e8cf"},
        "light": {"visited": "#bc4749", "stripe": "#6a994e", "dot": "#f2e8cf"},
    },
}

# Christmas stripes: 8px period at the output resolution, half of each period
# in the stripe color. Supersampling keeps the edges even instead of hatched.
STRIPE_PERIOD = 8
STRIPE_FRACTION = 0.5
STRIPE_SUPERSAMPLE = 4

PALETTE_NAMES = ("default", "halloween", "christmas", "auto")
FORMAT_NAMES = ("png", "svg", "both")

# ``auto`` follows the same UTC days as contrib-tetris.
AUTO_HOLIDAYS: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] = (
    ("halloween", ((10, 31),)),
    ("christmas", ((12, 24), (12, 25), (12, 26))),
)

# Names people type that Natural Earth's own labels do not already cover.
# Applied only when that folded key is still free, so the dataset wins.
COUNTRY_ALIASES = {
    "uk": "GBR",
    "u k": "GBR",
    "great britain": "GBR",
    "britain": "GBR",
    "uae": "ARE",
    "burma": "MMR",
    "drc": "COD",
    "dr congo": "COD",
}
STATE_ALIASES = {
    "washington dc": "District of Columbia",
    "washington d c": "District of Columbia",
    "d c": "District of Columbia",
}

_MISSING = object()
_ISO2 = re.compile(r"^[A-Za-z]{2}$")
_ISO3 = re.compile(r"^[A-Za-z]{3}$")


class TravelError(Exception):
    """A problem the CLI should print without a traceback."""


class ConfigError(TravelError):
    """The travel file is missing or not usable."""


class InputError(TravelError):
    """A CLI flag or action input is missing or not usable."""


class DataError(TravelError):
    """Map data is missing, corrupt, or could not be downloaded."""


@dataclass(frozen=True)
class City:
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class TravelConfig:
    countries: tuple[str, ...]
    us_states: tuple[str, ...]
    cities: tuple[City, ...]
    china_provinces: tuple[str, ...] = ()
    japan_prefectures: tuple[str, ...] = ()
    planned: tuple[City, ...] = ()
    planned_states: tuple[str, ...] = ()
    path: str | None = None

    @property
    def label(self) -> str:
        return self.path or "config"


@dataclass(frozen=True)
class ResolvedTravel:
    """Places matched to Natural Earth ids.

    ``countries`` are filled in full. ``states``, ``provinces``, and
    ``prefectures`` are the only parts of a country that get a color when
    that country itself is not listed. The rest of that country stays the
    plain land color. ``planned_states`` and ``planned_cities`` are drawn
    in the accent color and are not part of those visited sets.
    """

    countries: tuple[str, ...]
    states: tuple[str, ...]
    cities: tuple[City, ...]
    provinces: tuple[str, ...] = ()
    prefectures: tuple[str, ...] = ()
    planned_states: tuple[str, ...] = ()
    planned_cities: tuple[City, ...] = ()
    note: str | None = None


@dataclass(frozen=True)
class TravelStats:
    """Counts drawn on the map, plus the country total those counts are compared with.

    ``world_countries`` is every Natural Earth admin-0 country the map can
    draw, Antarctica excluded. Province and prefecture counts are zero when
    those units are not drawn, including when the whole country is filled
    instead.
    """

    countries: int
    world_countries: int
    us_states: int
    china_provinces: int
    japan_prefectures: int


@dataclass
class World:
    countries: object
    states: object
    provinces: object
    prefectures: object
    country_index: dict[str, str | None]
    state_index: dict[str, str | None]
    province_index: dict[str, str | None]
    prefecture_index: dict[str, str | None]
    country_names: tuple[str, ...]
    state_names: tuple[str, ...]
    province_names: tuple[str, ...]
    prefecture_names: tuple[str, ...]


@dataclass(frozen=True)
class RenderResult:
    dark_path: Path | None
    light_path: Path | None
    palette: str
    resolved: ResolvedTravel
    dark_svg_path: Path | None = None
    light_svg_path: Path | None = None
    badge_path: Path | None = None


def normalize_name(value: str) -> str:
    """Fold case, accents, and punctuation so ``Côte d'Ivoire`` matches a typed name."""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _planned_marker_id(name: str) -> str:
    """SVG group id ``planned-<name>``. Spaces and punctuation become hyphens.

    The id stays an XML Name, so ``Sample Cove`` is ``planned-Sample-Cove``.
    A single word such as ``Harbor`` stays ``planned-Harbor``.
    """
    text = unicodedata.normalize("NFKD", name)
    text = "".join(char for char in text if not unicodedata.combining(char))
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    if not slug:
        slug = "place"
    return f"planned-{slug}"


def resolve_palette(name: str, today: date) -> str:
    """Return the concrete palette for ``name`` on ``today``.

    ``default``, ``halloween``, and ``christmas`` are returned as given.
    ``auto`` uses halloween on 31 October, christmas on 24-26 December, and
    ``default`` on every other day. ``today`` is the calendar day to test.
    This does not read the clock; pass the current UTC date when the caller
    means now.
    """
    if name == "auto":
        key = (today.month, today.day)
        for palette, days in AUTO_HOLIDAYS:
            if palette not in PALETTES:
                raise TravelError(f"unknown palette {palette!r}")
            if key in days:
                return palette
        return "default"
    if name not in PALETTES:
        raise TravelError(f"unknown palette {name!r}")
    return name


def parse_format(raw: object) -> str:
    """Return ``png``, ``svg``, or ``both``, or raise InputError naming ``format``."""
    hint = "Use png for the two PNGs, svg for the two SVGs, or both to write all four."
    if not isinstance(raw, str) or raw.strip() == "":
        shown = "empty" if isinstance(raw, str) else repr(raw)
        raise InputError(f"format (--format) is {shown}, which is not a known format. {hint}")
    value = raw.strip().lower()
    if value not in FORMAT_NAMES:
        raise InputError(f"format (--format) is {raw!r}, which is not a known format. {hint}")
    return value


def parse_badge(raw: object) -> bool:
    """Return whether to write ``travel-badge.svg``.

    ``true`` and ``false`` are accepted in any case, with surrounding
    whitespace ignored. Anything else, including an empty value, raises
    InputError naming ``badge``.
    """
    hint = "Use true to write travel-badge.svg next to the map, or false to skip it."
    if not isinstance(raw, str) or raw.strip() == "":
        shown = "empty" if isinstance(raw, str) else repr(raw)
        raise InputError(f"badge (--badge) is {shown}, which is not true or false. {hint}")
    value = raw.strip().lower()
    if value not in {"true", "false"}:
        raise InputError(f"badge (--badge) is {raw!r}, which is not true or false. {hint}")
    return value == "true"


def parse_palette(raw: object) -> str:
    """Return a palette name, or raise InputError naming ``palette``."""
    hint = (
        "Use default for the green map, halloween for the orange map, "
        "christmas for the Coolors Christmas map, or auto to use halloween "
        "on 31 October (UTC), christmas on 24-26 December (UTC), and default "
        "every other day."
    )
    if not isinstance(raw, str) or raw.strip() == "":
        shown = "empty" if isinstance(raw, str) else repr(raw)
        raise InputError(f"palette (--palette) is {shown}, which is not a known palette. {hint}")
    value = raw.strip().lower()
    if value not in PALETTE_NAMES:
        raise InputError(f"palette (--palette) is {raw!r}, which is not a known palette. {hint}")
    return value


def parse_date(raw: str) -> date:
    """Return a ``YYYY-MM-DD`` date, or raise InputError naming ``date``."""
    hint = "Use YYYY-MM-DD, for example 2026-10-31."
    if not isinstance(raw, str) or raw.strip() == "":
        raise InputError(f"date (--date) is {raw!r}, which is not a calendar date. {hint}")
    text = raw.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) is None:
        raise InputError(f"date (--date) is {raw!r}, which is not a calendar date. {hint}")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise InputError(f"date (--date) is {raw!r}, which is not a calendar date. {hint}") from None


def cache_directory() -> Path:
    """Directory reused across runs so a download happens once."""
    override = os.environ.get("TRAVEL_FOOTPRINT_CACHE")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CACHE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".cache"
    return base / "travel-footprint"


def load_checksums(path: Path | None = None) -> dict[str, str]:
    """Read ``data/SHA256SUMS`` (hash, two spaces, filename)."""
    sums = path or (VENDOR_DIR / "SHA256SUMS")
    if not sums.is_file():
        raise DataError(
            f"checksum file {sums} is missing. "
            "travel-footprint needs data/SHA256SUMS to verify Natural Earth downloads."
        )
    found: dict[str, str] = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        digest, _, name = text.partition(" ")
        name = name.strip()
        if len(digest) != 64 or not name:
            raise DataError(f"checksum file {sums} has an unreadable line: {line!r}")
        found[name] = digest.lower()
    missing = [name for name in DATASET_NAMES if name not in found]
    if missing:
        raise DataError(f"checksum file {sums} does not list {', '.join(missing)}.")
    return found


def verify_sha256(path: Path, expected: str, label: str) -> None:
    """Raise DataError when ``path`` is not the pinned Natural Earth zip."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected.lower():
        raise DataError(
            f"{label} at {path} has sha256 {digest}, expected {expected.lower()}. "
            "Refusing to draw a map from map data that does not match data/SHA256SUMS."
        )


def download_file(url: str, dest: Path) -> None:
    """Download ``url`` to ``dest``. A failed download leaves no partial file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            payload = response.read()
        temporary.write_bytes(payload)
        os.replace(temporary, dest)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        temporary.unlink(missing_ok=True)
        reason = getattr(exc, "reason", exc)
        raise DataError(
            f"could not download {dest.name} from {url} ({reason}). "
            "The same files are vendored in data/ when the repository is complete."
        ) from exc


def locate_dataset(
    name: str,
    *,
    vendor_dir: Path | None = None,
    cache_dir: Path | None = None,
    fetch=download_file,
    verify: bool = True,
) -> Path:
    """Return a verified zip, preferring ``data/`` and then the download cache.

    ``fetch`` is called only when both locations lack a usable file. A second
    call with the same cache hits the file written by the first.
    """
    if name not in DATASET_NAMES:
        raise DataError(f"unknown map dataset {name!r}.")
    vendor_root = VENDOR_DIR if vendor_dir is None else vendor_dir
    vendored = vendor_root / name
    cached_root = cache_directory() if cache_dir is None else cache_dir
    cached = cached_root / name
    path = vendored if vendored.is_file() else cached
    if not path.is_file():
        url = DATASET_URLS.get(name)
        if url is None:
            raise DataError(
                f"{name} is missing from {vendor_root}. "
                "This file ships in data/ and is not downloaded automatically."
            )
        cached_root.mkdir(parents=True, exist_ok=True)
        fetch(url, cached)
        path = cached
        if not path.is_file() or path.stat().st_size == 0:
            raise DataError(f"download of {name} did not produce a file at {path}.")
    if verify:
        expected = load_checksums().get(name)
        if expected is None:
            raise DataError(f"checksum file does not list {name}.")
        try:
            verify_sha256(path, expected, name)
        except DataError:
            if path == cached:
                path.unlink(missing_ok=True)
            raise
    return path


def _open_zip(name: str):
    import geopandas as gpd

    path = locate_dataset(name)
    try:
        return gpd.read_file(path)
    except Exception as exc:
        raise DataError(
            f"could not read {name} at {path}. The file is not a usable shapefile ({exc})."
        ) from exc


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "-99", "none"}:
        return None
    return text


def _put(index: dict[str, str | None], key: str, value: str) -> None:
    if not key:
        return
    current = index.get(key, _MISSING)
    if current is _MISSING:
        index[key] = value
    elif current != value:
        index[key] = None


def _add_if_free(index: dict[str, str | None], label: object, value: str) -> None:
    """Index a fallback code without displacing a code already assigned."""
    text = _text(label)
    if text is None:
        return
    folded = normalize_name(text)
    if not folded or folded in index:
        return
    index[folded] = value


def _add_label(index: dict[str, str | None], label: object, value: str) -> None:
    text = _text(label)
    if text is None:
        return
    folded = normalize_name(text)
    if not folded or folded == "99":
        return
    _put(index, folded, value)
    compact = folded.replace(" ", "")
    if compact != folded:
        _put(index, compact, value)


@lru_cache(maxsize=1)
def read_admin0():
    """Unprojected countries, Antarctica removed."""
    frame = _open_zip(COUNTRIES_ZIP)
    keep = [
        "ADM0_A3",
        "ISO_A2",
        "ISO_A3",
        "ISO_A2_EH",
        "ISO_A3_EH",
        "NAME",
        "NAME_LONG",
        "NAME_EN",
        "ADMIN",
        "NAME_ALT",
        "CONTINENT",
        "TYPE",
        "geometry",
    ]
    missing = [column for column in keep if column not in frame.columns]
    if missing:
        raise DataError(
            f"{COUNTRIES_ZIP} is missing {', '.join(missing)}. "
            "travel-footprint expects the Natural Earth admin-0 countries fields."
        )
    frame = frame.loc[:, keep].copy()
    frame = frame[frame["ADM0_A3"].map(_text).notna()]
    frame = frame[frame["ADM0_A3"] != "ATA"]
    geometry = frame.geometry
    frame = frame[geometry.notna() & ~geometry.is_empty].copy()
    frame["adm0_a3"] = frame["ADM0_A3"].map(lambda value: str(value).strip())
    return frame


def _read_admin1(dataset: str, adm0: str, types: tuple[str, ...]):
    """One country's first-level units from a Natural Earth admin-1 extract."""
    frame = _open_zip(dataset)
    needed = ["adm0_a3", "name", "postal", "iso_3166_2", "type_en", "geometry"]
    missing = [column for column in needed if column not in frame.columns]
    if missing:
        raise DataError(
            f"{dataset} is missing {', '.join(missing)}. "
            "travel-footprint expects the Natural Earth admin-1 fields."
        )
    columns = needed + [column for column in ("name_en", "name_alt") if column in frame.columns]
    frame = frame.loc[:, columns].copy()
    frame = frame[frame["adm0_a3"].map(_text) == adm0]
    frame = frame[frame["type_en"].isin(types)]
    geometry = frame.geometry
    frame = frame[geometry.notna() & ~geometry.is_empty].copy()
    frame["name"] = frame["name"].map(lambda value: str(value).strip())
    if frame.empty:
        raise DataError(f"{dataset} has no {adm0} subdivisions to highlight.")
    return frame


@lru_cache(maxsize=1)
def read_admin1_usa():
    """Unprojected US states and the District of Columbia."""
    return _read_admin1(STATES_ZIP, "USA", ("State", "Federal District"))


@lru_cache(maxsize=1)
def read_admin1_china():
    """Unprojected Chinese provinces, autonomous regions, and municipalities."""
    return _read_admin1(
        STATES_ZIP,
        "CHN",
        ("Province", "Autonomous Region", "Municipality"),
    )


@lru_cache(maxsize=1)
def read_admin1_japan():
    """Unprojected Japanese prefectures, including Tokyo, Kyoto, Osaka, and Hokkaido."""
    return _read_admin1(
        JAPAN_ZIP,
        "JPN",
        ("Prefecture", "Urban Prefecture", "Metropolis", "Circuit"),
    )


def build_country_index(frame) -> tuple[dict[str, str | None], tuple[str, ...]]:
    index: dict[str, str | None] = {}
    displays: set[str] = set()
    for row in frame.itertuples(index=False):
        code = str(row.adm0_a3).strip()
        _add_label(index, code, code)
        iso2 = _text(row.ISO_A2)
        if iso2 and _ISO2.fullmatch(iso2):
            _add_label(index, iso2, code)
        elif _text(row.ISO_A2_EH) and _ISO2.fullmatch(_text(row.ISO_A2_EH) or ""):
            # Natural Earth leaves ISO_A2 as -99 for a few countries and stores
            # the code in ISO_A2_EH. Use it only when that code is still free,
            # so a territory cannot take Australia's AU.
            _add_if_free(index, _text(row.ISO_A2_EH), code)
        iso3 = _text(row.ISO_A3)
        if iso3 and _ISO3.fullmatch(iso3):
            _add_label(index, iso3, code)
        elif _text(row.ISO_A3_EH) and _ISO3.fullmatch(_text(row.ISO_A3_EH) or ""):
            _add_if_free(index, _text(row.ISO_A3_EH), code)
        for label in (row.NAME, row.NAME_LONG, row.NAME_EN, row.ADMIN):
            _add_label(index, label, code)
        alt = _text(row.NAME_ALT)
        if alt:
            for part in alt.split("|"):
                _add_label(index, part, code)
        display = _text(row.NAME_EN) or _text(row.NAME) or code
        displays.add(display)
    for alias, code in COUNTRY_ALIASES.items():
        if code in set(frame["adm0_a3"]):
            _add_label(index, alias, code)
    return index, tuple(sorted(displays))


def build_state_index(
    frame,
    aliases: dict[str, str] | None = None,
) -> tuple[dict[str, str | None], tuple[str, ...]]:
    """Index subdivision names. The Natural Earth ``name`` wins over a colliding label.

    The District of Columbia's English name is ``Washington``, which would
    otherwise hide Washington state. ``aliases`` defaults to the US extras.
    Pass an empty mapping for another country.
    """
    if aliases is None:
        aliases = STATE_ALIASES
    index: dict[str, str | None] = {}
    displays: set[str] = set()
    rows = list(frame.itertuples(index=False))
    for row in rows:
        canonical = str(row.name).strip()
        _add_label(index, canonical, canonical)
        displays.add(canonical)
    for row in rows:
        canonical = str(row.name).strip()
        if hasattr(row, "name_en"):
            _add_if_free(index, row.name_en, canonical)
        alt = _text(getattr(row, "name_alt", None))
        if alt:
            for part in alt.split("|"):
                _add_if_free(index, part, canonical)
        for field in ("postal", "iso_3166_2"):
            if hasattr(row, field):
                _add_if_free(index, getattr(row, field), canonical)
    for alias, canonical in aliases.items():
        if canonical in displays:
            _add_if_free(index, alias, canonical)
    return index, tuple(sorted(displays))


def display_lon(lon: float) -> float:
    """Longitude in the Pacific-centred frame. West of 30°W shifts by +360°."""
    return lon + 360.0 if lon < SEAM else lon


def shift_geometry(geom):
    """Move the part west of 30°W by +360° so the Pacific is centred."""
    if geom is None or geom.is_empty:
        return geom
    if geom.bounds[0] >= SEAM:
        return geom
    west = geom.intersection(_WEST)
    east = geom.intersection(_EAST)
    pieces = []
    if not west.is_empty:
        pieces.append(translate(west, xoff=360.0))
    if not east.is_empty:
        pieces.append(east)
    if not pieces:
        return geom
    if len(pieces) == 1:
        return pieces[0]
    return unary_union(pieces)


def _project_geom(geom, tolerance: float):
    if geom is None or geom.is_empty:
        return geom
    if not geom.is_valid:
        geom = geom.buffer(0)
    simplified = geom.simplify(tolerance, preserve_topology=True)
    return shift_geometry(simplified)


def project_frame(frame, tolerance: float):
    """Return a copy with simplified, Pacific-shifted geometries."""
    import geopandas as gpd

    projected = frame.copy()
    projected.geometry = gpd.GeoSeries(
        [_project_geom(geom, tolerance) for geom in frame.geometry],
        index=frame.index,
        crs=frame.crs,
    )
    return projected


@lru_cache(maxsize=1)
def load_world() -> World:
    """Read, index, and project Natural Earth. Cached for the process."""
    countries = read_admin0()
    states = read_admin1_usa()
    provinces = read_admin1_china()
    prefectures = read_admin1_japan()
    country_index, country_names = build_country_index(countries)
    state_index, state_names = build_state_index(states)
    province_index, province_names = build_state_index(provinces, aliases={})
    prefecture_index, prefecture_names = build_state_index(prefectures, aliases={})
    return World(
        countries=project_frame(countries, 0.08),
        states=project_frame(states, 0.01),
        provinces=project_frame(provinces, 0.01),
        prefectures=project_frame(prefectures, 0.01),
        country_index=country_index,
        state_index=state_index,
        province_index=province_index,
        prefecture_index=prefecture_index,
        country_names=country_names,
        state_names=state_names,
        province_names=province_names,
        prefecture_names=prefecture_names,
    )


def suggest_names(token: str, names: tuple[str, ...] | list[str], *, limit: int = 3) -> list[str]:
    """Human labels the token almost matches, for an error message."""
    folded = normalize_name(token)
    if not folded:
        return []
    word_hits = []
    fuzzy_hits = []
    for name in names:
        label = normalize_name(name)
        if folded == label:
            continue
        if folded in label.split():
            word_hits.append(name)
            continue
        if len(folded) <= 3:
            continue
        ratio = difflib.SequenceMatcher(None, folded, label).ratio()
        if ratio >= 0.72:
            fuzzy_hits.append((-ratio, name))
    word_hits.sort()
    fuzzy_hits.sort()
    ordered = word_hits + [name for _, name in fuzzy_hits]
    unique: list[str] = []
    for name in ordered:
        if name not in unique:
            unique.append(name)
        if len(unique) == limit:
            break
    return unique


def _did_you_mean(options: list[str]) -> str:
    if not options:
        return ""
    if len(options) == 1:
        return f" Did you mean {options[0]}?"
    if len(options) == 2:
        return f" Did you mean {options[0]} or {options[1]}?"
    return f" Did you mean {', '.join(options[:-1])}, or {options[-1]}?"


def resolve_token(
    token: str,
    index: dict[str, str | None],
    names: tuple[str, ...] | list[str],
    *,
    field: str,
    example: str,
) -> str:
    """Match one config entry, or raise ConfigError with a suggestion."""
    folded = normalize_name(token)
    compact = folded.replace(" ", "")
    found = _MISSING
    for key in (folded, compact):
        if key and key in index:
            found = index[key]
            break
    if found is _MISSING:
        hint = _did_you_mean(suggest_names(token, names))
        raise ConfigError(
            f"{field} entry {token!r} is not recognized. {example}{hint}"
        )
    if found is None:
        raise ConfigError(
            f"{field} entry {token!r} matches more than one place. {example}"
        )
    return found


# YAML ---------------------------------------------------------------------

class ConfigLoader(yaml.SafeLoader):
    """Safe YAML that keeps ``NO`` as a string (Norway) instead of a boolean."""


ConfigLoader.yaml_implicit_resolvers = {
    key: list(value) for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for _key, _resolvers in list(ConfigLoader.yaml_implicit_resolvers.items()):
    ConfigLoader.yaml_implicit_resolvers[_key] = [
        (tag, pattern)
        for tag, pattern in _resolvers
        if tag != "tag:yaml.org,2002:bool"
    ]


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.Node, deep: bool = False):
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ConfigError(
                f"YAML key {key!r} is repeated. Each key may appear once."
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


ConfigLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)

_ALLOWED_KEYS = (
    "countries",
    "us_states",
    "china_provinces",
    "japan_prefectures",
    "cities",
    "planned",
    "planned_states",
)
_CONFIG_SHAPE = (
    "countries, us_states, china_provinces, japan_prefectures, cities, "
    "planned, and planned_states"
)
_CITY_KEYS = {"name", "lat", "latitude", "lon", "lng", "long", "longitude"}
_LIST_EXAMPLES = {
    "countries": (
        "Use a list of ISO 3166-1 alpha-2 or alpha-3 codes or English names, "
        "for example [NZ, Japan]."
    ),
    "us_states": "Use a list of US state names or USPS codes, for example [Colorado, ME].",
    "china_provinces": (
        "Use a list of Chinese province, autonomous region, or municipality names, "
        "or ISO 3166-2 codes, for example [Zhejiang, CN-ZJ]."
    ),
    "japan_prefectures": (
        "Use a list of Japanese prefecture names or ISO 3166-2 codes, "
        "for example [Kyoto, JP-26]."
    ),
    "planned_states": (
        "Use a list of US state names or USPS codes, for example [Oregon, OR]. "
        "These are drawn as planned and are not counted as visited."
    ),
}


def _yaml_error_text(exc: yaml.YAMLError) -> str:
    text = str(exc).strip().splitlines()
    return text[0] if text else "the file could not be parsed"


def _key_hint(unknown: list, allowed: tuple[str, ...]) -> str:
    """Return " Did you mean ...?" for misspelled keys, or an empty string."""
    pairs = []
    for key in unknown:
        if not isinstance(key, str):
            continue
        close = difflib.get_close_matches(key.strip().lower(), allowed, n=1, cutoff=0.75)
        if close:
            pairs.append(f"{close[0]!r} for {key!r}")
    if not pairs:
        return ""
    return f" Did you mean {', '.join(pairs)}?"


def parse_config(text: str, *, path: str | None = None) -> TravelConfig:
    """Parse and structurally validate a travel YAML document."""
    where = path or "config"
    try:
        data = yaml.load(text, Loader=ConfigLoader)
    except ConfigError:
        raise
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"{where} is not valid YAML ({_yaml_error_text(exc)}). "
            f"Use a mapping with {_CONFIG_SHAPE}."
        ) from exc
    if data is None:
        raise ConfigError(
            f"{where} is empty. List {_CONFIG_SHAPE}. "
            "See travel.example.yml."
        )
    if not isinstance(data, dict):
        raise ConfigError(
            f"{where} must be a YAML mapping of {_CONFIG_SHAPE}, "
            f"not {type(data).__name__}."
        )
    unknown = [key for key in data if key not in _ALLOWED_KEYS]
    if unknown:
        noun = "key" if len(unknown) == 1 else "keys"
        names = ", ".join(repr(key) for key in unknown)
        raise ConfigError(
            f"{where} has unknown {noun} {names}.{_key_hint(unknown, _ALLOWED_KEYS)} "
            f"Supported keys are {_CONFIG_SHAPE}. "
            "Other subdivisions are not supported yet."
        )
    cities = _cities(_section(data, "cities", where), where)
    planned = _cities(_section(data, "planned", where), where, field="planned")
    _reject_planned_cities_already_visited(cities, planned, where)
    return TravelConfig(
        countries=_string_list(_section(data, "countries", where), "countries", where),
        us_states=_string_list(_section(data, "us_states", where), "us_states", where),
        china_provinces=_string_list(
            _section(data, "china_provinces", where), "china_provinces", where
        ),
        japan_prefectures=_string_list(
            _section(data, "japan_prefectures", where), "japan_prefectures", where
        ),
        cities=cities,
        planned=planned,
        planned_states=_string_list(
            _section(data, "planned_states", where), "planned_states", where
        ),
        path=path,
    )


def _reject_planned_cities_already_visited(
    cities: tuple[City, ...], planned: tuple[City, ...], where: str
) -> None:
    """A city is either visited or planned, matching the planned_states rule."""
    visited = {normalize_name(city.name): city.name for city in cities}
    for index, city in enumerate(planned, start=1):
        earlier = visited.get(normalize_name(city.name))
        if earlier is not None:
            raise ConfigError(
                f"{where}: planned entry {index} ({city.name!r}) is already listed under "
                f"cities as {earlier!r}. A city is either visited or planned. "
                "Once you have been there, remove it from planned."
            )


def _section(data: dict, field: str, where: str) -> object:
    """Return a present value. Missing keys become None; explicit null is an error."""
    if field not in data:
        return None
    value = data[field]
    if value is None:
        raise ConfigError(
            f"{where}: {field} is null. Omit the key, or use an empty list if there is nothing to draw."
        )
    return value


def load_config(path: Path) -> TravelConfig:
    """Read ``path`` as travel YAML."""
    if not path.is_file():
        raise ConfigError(
            f"config is {str(path)!r}, which does not exist. "
            f"Pass a YAML file of {_CONFIG_SHAPE}, for example travel.yml."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"config {path} could not be read ({exc}).") from exc
    return parse_config(text, path=str(path))


def _string_list(value: object, field: str, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    example = _LIST_EXAMPLES.get(field, "Use a list of names.")
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ConfigError(f"{where}: {field} is {value!r}, which is not a list. {example}")
    items: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value, start=1):
        if isinstance(item, bool) or not isinstance(item, str):
            raise ConfigError(
                f"{where}: {field} entry {index} is {item!r}, which is not text. {example} "
                "Quote two-letter codes if a different YAML loader would read them as booleans."
            )
        text = item.strip()
        if text == "":
            raise ConfigError(f"{where}: {field} entry {index} is empty. {example}")
        folded = normalize_name(text)
        if folded in seen:
            raise ConfigError(
                f"{where}: {field} entry {index} ({text!r}) repeats an earlier entry. List it once."
            )
        seen.add(folded)
        items.append(text)
    return tuple(items)


def _cities(value: object, where: str, field: str = "cities") -> tuple[City, ...]:
    if value is None:
        return ()
    example = (
        "Each city needs a name, lat (or latitude) from -90 to 90, "
        "and lon (or longitude) from -180 to 180."
    )
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ConfigError(f"{where}: {field} is {value!r}, which is not a list. {example}")
    cities: list[City] = []
    seen_names: set[str] = set()
    seen_ids: set[str] = set()
    for index, item in enumerate(value, start=1):
        city = _one_city(item, index, where, example, field)
        if field == "planned":
            folded = normalize_name(city.name)
            marker = _planned_marker_id(city.name)
            if folded in seen_names or marker in seen_ids:
                raise ConfigError(
                    f"{where}: {field} entry {index} ({city.name!r}) repeats an earlier name. "
                    "List each planned city once."
                )
            seen_names.add(folded)
            seen_ids.add(marker)
        cities.append(city)
    return tuple(cities)


def _one_city(item: object, index: int, where: str, example: str, field: str = "cities") -> City:
    label = f"{where}: {field} entry {index}"
    if not isinstance(item, dict):
        raise ConfigError(f"{label} is {item!r}, which is not a mapping. {example}")
    unknown = [key for key in item if key not in _CITY_KEYS]
    if unknown:
        names = ", ".join(repr(key) for key in unknown)
        raise ConfigError(
            f"{label} has unknown key {names}.{_key_hint(unknown, tuple(sorted(_CITY_KEYS)))} {example}"
        )
    if "name" not in item:
        raise ConfigError(f"{label} is missing name. {example}")
    name = item["name"]
    if isinstance(name, bool) or not isinstance(name, str) or name.strip() == "":
        raise ConfigError(f"{label} name is {name!r}, which is not a non-empty name. {example}")
    if any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ConfigError(f"{label} name {name!r} contains a control character. {example}")
    lat = _coordinate(item, ("lat", "latitude"), f"{label} lat", -90.0, 90.0, example)
    lon = _coordinate(item, ("lon", "lng", "long", "longitude"), f"{label} lon", -180.0, 180.0, example)
    return City(name=name.strip(), lat=lat, lon=lon)


def _coordinate(
    item: dict,
    keys: tuple[str, ...],
    label: str,
    low: float,
    high: float,
    example: str,
) -> float:
    present = [key for key in keys if key in item]
    if not present:
        raise ConfigError(f"{label} is missing. {example}")
    if len(present) > 1:
        names = " and ".join(present)
        raise ConfigError(f"{label} sets both {names}. Use one. {example}")
    value = _finite_number(item[present[0]], label, example)
    if value < low or value > high:
        raise ConfigError(
            f"{label} is {value}, which is outside {low:g} to {high:g}. {example}"
        )
    return value


def _finite_number(value: object, label: str, example: str) -> float:
    if isinstance(value, bool) or isinstance(value, (list, dict)) or value is None:
        raise ConfigError(f"{label} is {value!r}, which is not a number. {example}")
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            raise ConfigError(f"{label} is {value!r}, which is not a number. {example}") from None
    if not isinstance(value, (int, float)):
        raise ConfigError(f"{label} is {value!r}, which is not a number. {example}")
    number = float(value)
    if not math.isfinite(number):
        raise ConfigError(f"{label} is {value!r}, which is not a finite number. {example}")
    return number


def _resolve_named_list(
    entries: tuple[str, ...],
    *,
    index: dict[str, str | None],
    names: tuple[str, ...],
    where: str,
    field: str,
    noun: str,
    example: str,
) -> list[str]:
    """Match one list of places. Repeats of the same place are rejected."""
    resolved: list[str] = []
    seen: dict[str, str] = {}
    for entry in entries:
        canonical = resolve_token(
            entry,
            index,
            names,
            field=f"{where}: {field}",
            example=example,
        )
        if canonical in seen:
            raise ConfigError(
                f"{where}: {field} entry {entry!r} is the same {noun} as "
                f"{seen[canonical]!r}. List it once."
            )
        seen[canonical] = entry
        resolved.append(canonical)
    return resolved


def _paint_unless_country_listed(
    resolved: list[str],
    countries: tuple[str, ...] | list[str],
    adm0: str,
    field: str,
) -> tuple[tuple[str, ...], str | None]:
    """Drop subdivisions when their country is already filled in full."""
    if resolved and adm0 in countries:
        return (), (
            f"{adm0} is listed under countries, so the whole country is filled "
            f"and {field} are not drawn separately."
        )
    return tuple(resolved), None


def resolve_travel(config: TravelConfig, world: World | None = None) -> ResolvedTravel:
    """Match config entries to Natural Earth ids."""
    world = load_world() if world is None else world
    where = config.label
    country_example = (
        "Use an ISO 3166-1 alpha-2 or alpha-3 code or an English name, for example NZ or New Zealand."
    )
    countries = _resolve_named_list(
        config.countries,
        index=world.country_index,
        names=world.country_names,
        where=where,
        field="countries",
        noun="country",
        example=country_example,
    )
    state_example = "Use a state name or USPS code, for example Wyoming or WY."
    matched_states = _resolve_named_list(
        config.us_states,
        index=world.state_index,
        names=world.state_names,
        where=where,
        field="us_states",
        noun="state",
        example=state_example,
    )
    states, state_note = _paint_unless_country_listed(
        matched_states,
        countries,
        "USA",
        "us_states",
    )
    planned_states = _resolve_named_list(
        config.planned_states,
        index=world.state_index,
        names=world.state_names,
        where=where,
        field="planned_states",
        noun="state",
        example=(
            "Use a state name or USPS code, for example Oregon or OR. "
            "Planned states are drawn separately and are not counted as visited."
        ),
    )
    visited_states = set(matched_states)
    for entry, canonical in zip(config.planned_states, planned_states):
        if canonical in visited_states:
            raise ConfigError(
                f"{where}: planned_states entry {entry!r} is already listed under us_states. "
                "A state is either visited or planned. Planned places are not counted as visited."
            )
    provinces, province_note = _paint_unless_country_listed(
        _resolve_named_list(
            config.china_provinces,
            index=world.province_index,
            names=world.province_names,
            where=where,
            field="china_provinces",
            noun="province",
            example=(
                "Use a province, autonomous region, or municipality name, or an "
                "ISO 3166-2 code, for example Zhejiang or CN-ZJ."
            ),
        ),
        countries,
        "CHN",
        "china_provinces",
    )
    prefectures, prefecture_note = _paint_unless_country_listed(
        _resolve_named_list(
            config.japan_prefectures,
            index=world.prefecture_index,
            names=world.prefecture_names,
            where=where,
            field="japan_prefectures",
            noun="prefecture",
            example="Use a prefecture name or an ISO 3166-2 code, for example Kyoto or JP-26.",
        ),
        countries,
        "JPN",
        "japan_prefectures",
    )
    notes = [note for note in (state_note, province_note, prefecture_note) if note]
    return ResolvedTravel(
        countries=tuple(countries),
        states=states,
        provinces=provinces,
        prefectures=prefectures,
        cities=config.cities,
        planned_states=tuple(planned_states),
        planned_cities=config.planned,
        note=" ".join(notes) if notes else None,
    )


# Drawing ------------------------------------------------------------------

def _subset(frame, column: str, keys: tuple[str, ...]):
    if not keys:
        return frame.iloc[0:0]
    return frame[frame[column].isin(keys)]


def _visited_frames(world: World, resolved: ResolvedTravel):
    """Visited shapes in paint order, with the matplotlib line width in points.

    A listed country is one layer. Listed states, provinces, and prefectures are
    the others. Callers omit a layer when its frame is empty, so the rest of
    that country stays the plain land color.
    """
    return (
        ("states", _subset(world.states, "name", resolved.states), SUBDIVISION_LINEWIDTH),
        ("provinces", _subset(world.provinces, "name", resolved.provinces), SUBDIVISION_LINEWIDTH),
        ("prefectures", _subset(world.prefectures, "name", resolved.prefectures), SUBDIVISION_LINEWIDTH),
        ("countries", _subset(world.countries, "adm0_a3", resolved.countries), COUNTRY_LINEWIDTH),
    )


def _paint(ax, frame, *, face: str | None, edge: str, width: float, zorder: int) -> None:
    if frame.empty:
        return
    if face is None:
        frame.plot(ax=ax, facecolor="none", edgecolor=edge, linewidth=width, zorder=zorder)
    else:
        frame.plot(ax=ax, color=face, edgecolor=edge, linewidth=width, zorder=zorder)


def _polygons(geom):
    """Yield polygon parts, including pieces inside a collection."""
    if geom is None or geom.is_empty:
        return
    kind = geom.geom_type
    if kind == "Polygon":
        yield geom
    elif kind in {"MultiPolygon", "GeometryCollection"}:
        for part in geom.geoms:
            yield from _polygons(part)


def _stripe_mask(width: int, height: int) -> np.ndarray:
    """Even 45-degree bands, one value per output pixel, antialiased by supersampling."""
    step = STRIPE_SUPERSAMPLE
    period = STRIPE_PERIOD
    fraction = STRIPE_FRACTION
    y_coords, x_coords = np.mgrid[0 : height * step, 0 : width * step]
    y_coords = y_coords / step
    x_coords = x_coords / step
    # '/' bands. y grows downward, matching an image whose origin is the top.
    band = ((x_coords + y_coords) % period) < (period * fraction)
    folded = band.astype(np.float32).reshape(height, step, width, step)
    return folded.mean(axis=(1, 3))


def _clip_path(geometries) -> MplPath | None:
    vertices: list[tuple[float, float]] = []
    codes: list[int] = []
    for geom in geometries:
        for polygon in _polygons(geom):
            rings = [polygon.exterior, *polygon.interiors]
            for ring in rings:
                coords = [(float(x), float(y)) for x, y in ring.coords]
                if len(coords) < 4:
                    continue
                vertices.extend(coords)
                codes.append(MplPath.MOVETO)
                codes.extend([MplPath.LINETO] * (len(coords) - 2))
                codes.append(MplPath.CLOSEPOLY)
    if not vertices:
        return None
    return MplPath(vertices, codes)


def paint_stripes(ax, geometries, color: str) -> None:
    """Clip a pixel-aligned stripe image to ``geometries``.

    The period is ``STRIPE_PERIOD`` output pixels, so the bands stay even.
    Matplotlib's hatch is not used; it does not land on the pixel grid.
    """
    figure = ax.figure
    width = int(round(figure.get_figwidth() * figure.get_dpi()))
    height = int(round(figure.get_figheight() * figure.get_dpi()))
    if width <= 0 or height <= 0:
        raise TravelError("the map figure has no pixel size, so stripes cannot be aligned.")
    clip = _clip_path(geometries)
    if clip is None:
        return
    mask = _stripe_mask(width, height)
    image = np.zeros((height, width, 4), dtype=np.float32)
    image[..., :3] = to_rgb(color)
    image[..., 3] = mask
    patch = PathPatch(clip, transform=ax.transData, facecolor="none", edgecolor="none", linewidth=0)
    ax.add_patch(patch)
    artist = ax.imshow(
        image,
        extent=(0, 1, 0, 1),
        transform=ax.transAxes,
        interpolation="nearest",
        aspect="auto",
        origin="upper",
        zorder=3,
    )
    artist.set_clip_path(patch)


def draw_map(ax, world: World, resolved: ResolvedTravel, theme: str, palette: str) -> None:
    """Draw one theme. ``palette`` must already be concrete, not ``auto``."""
    if theme not in THEMES:
        raise TravelError(f"unknown theme {theme!r}")
    if palette not in PALETTES:
        raise TravelError(f"unknown palette {palette!r}")
    chrome = THEMES[theme]
    ink = PALETTES[palette][theme]
    ax.set_facecolor(chrome["background"])
    countries = world.countries
    _paint(
        ax,
        countries,
        face=chrome["land"],
        edge=chrome["edge"],
        width=LAND_LINEWIDTH,
        zorder=1,
    )
    # Subdivisions share the visited color. A listed country is filled in full
    # and its subdivisions are already omitted from ``resolved``.
    visited_layers = _visited_frames(world, resolved)
    stripe = ink.get("stripe")
    if stripe is None:
        for _name, frame, width in visited_layers:
            _paint(ax, frame, face=ink["visited"], edge=chrome["edge"], width=width, zorder=2)
    else:
        for _name, frame, _width in visited_layers:
            _paint(ax, frame, face=ink["visited"], edge="none", width=0, zorder=2)
        geometries = [geom for _name, frame, _width in visited_layers for geom in frame.geometry]
        paint_stripes(ax, geometries, stripe)
        for _name, frame, width in visited_layers:
            _paint(ax, frame, face=None, edge=chrome["edge"], width=width, zorder=4)
    if resolved.cities:
        xs = [display_lon(city.lon) for city in resolved.cities]
        ys = [city.lat for city in resolved.cities]
        ax.scatter(
            xs,
            ys,
            s=CITY_HALO_AREA,
            color=ink["visited"],
            alpha=CITY_HALO_ALPHA,
            zorder=5,
            linewidths=0,
        )
        ax.scatter(
            xs,
            ys,
            s=CITY_DOT_AREA,
            color=ink["dot"],
            edgecolor=ink["visited"],
            linewidths=CITY_DOT_LINEWIDTH,
            zorder=6,
        )
    _draw_planned(ax, world, resolved, ink["visited"])
    ax.set_xlim(*MAP_XLIM)
    ax.set_ylim(*MAP_YLIM)
    ax.set_aspect("equal", adjustable="datalim")
    ax.axis("off")


def _scatter_area_for_px(radius_px: float) -> float:
    """Pixel radius on the PNG as a matplotlib scatter area, in points squared."""
    radius_pt = radius_px * 72.0 / FIG_DPI
    return math.pi * radius_pt * radius_pt


def _draw_planned(ax, world: World, resolved: ResolvedTravel, color: str) -> None:
    """Static planned fill and dot. Animation is added only when writing SVG."""
    frame = _subset(world.states, "name", resolved.planned_states)
    if not frame.empty:
        frame.plot(
            ax=ax,
            color=color,
            edgecolor="none",
            linewidth=0,
            alpha=PLANNED_FILL_ALPHA,
            zorder=4,
        )
        frame.plot(
            ax=ax,
            facecolor="none",
            edgecolor=color,
            linewidth=PLANNED_EDGE_WIDTH,
            linestyle=(0, (PLANNED_DASH_ON, PLANNED_DASH_OFF)),
            zorder=4,
        )
    if not resolved.planned_cities:
        return
    xs = [display_lon(city.lon) for city in resolved.planned_cities]
    ys = [city.lat for city in resolved.planned_cities]
    ax.scatter(
        xs,
        ys,
        s=_scatter_area_for_px(PLANNED_DOT_RADIUS),
        color=color,
        zorder=7,
        linewidths=0,
    )


def _save_figure(fig, path: Path, background: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=".travel-map-", suffix=".png", dir=path.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        fig.savefig(temporary, facecolor=background, edgecolor=background, dpi=FIG_DPI)
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DataError(f"could not write {path} ({exc}).") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        plt.close(fig)


def _num(value: float) -> str:
    """Short decimal for an SVG coordinate. One user unit is one PNG pixel."""
    rounded = round(float(value), 2)
    if rounded == 0:
        return "0"
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _points_to_px(points: float) -> float:
    """Matplotlib point size as a pixel on the PNG, which is one SVG user unit."""
    return points * FIG_DPI / 72.0


def _marker_radius_px(area: float) -> float:
    """Scatter marker area, in points squared, as a pixel radius."""
    return math.sqrt(area / math.pi) * FIG_DPI / 72.0


def _svg_xy(lon: float, lat: float) -> tuple[float, float]:
    """Map a Pacific-centred longitude and latitude into the SVG viewBox.

    SVG y grows downward, so north is the top of the 1200 by 474 frame.
    """
    x = (lon - MAP_XLIM[0]) / (MAP_XLIM[1] - MAP_XLIM[0]) * SVG_WIDTH
    y = (MAP_YLIM[1] - lat) / (MAP_YLIM[1] - MAP_YLIM[0]) * SVG_HEIGHT
    return x, y


def _path_data(geometries) -> str:
    """SVG path data for polygon rings. Holes stay holes under the even-odd rule."""
    chunks: list[str] = []
    for geom in geometries:
        for polygon in _polygons(geom):
            for ring in (polygon.exterior, *polygon.interiors):
                coords = list(ring.coords)
                if len(coords) >= 2 and coords[0] == coords[-1]:
                    coords = coords[:-1]
                if len(coords) < 3:
                    continue
                pairs = []
                for coord in coords:
                    x, y = _svg_xy(float(coord[0]), float(coord[1]))
                    pairs.append(f"{_num(x)} {_num(y)}")
                chunks.append("M " + " L ".join(pairs) + " Z")
    return " ".join(chunks)


def _stripe_tile_polygons() -> tuple[tuple[tuple[float, float], ...], ...]:
    """Green part of one Christmas stripe tile. Y grows downward, as in the PNG.

    A pixel is green when ``(x + y) % STRIPE_PERIOD < STRIPE_PERIOD * STRIPE_FRACTION``,
    the same test as ``_stripe_mask``. The tile repeats every ``STRIPE_PERIOD`` pixels,
    which is 8px on the 1200 by 474 map, half red and half green.
    """
    period = float(STRIPE_PERIOD)
    band = period * STRIPE_FRACTION
    return (
        ((0.0, 0.0), (band, 0.0), (0.0, band)),
        ((period, 0.0), (period, band), (band, period), (0.0, period)),
    )


def _points_attr(pairs: tuple[tuple[float, float], ...]) -> str:
    return " ".join(f"{_num(x)},{_num(y)}" for x, y in pairs)


def _svg_document(world: World, resolved: ResolvedTravel, theme: str, palette: str) -> str:
    """One map as SVG text. ``palette`` must already be concrete."""
    chrome = THEMES[theme]
    ink = PALETTES[palette][theme]
    layers: list[tuple[str, str, float]] = []
    for name, frame, width in _visited_frames(world, resolved):
        data = _path_data(frame.geometry)
        if data:
            layers.append((name, data, _points_to_px(width)))
    land = _path_data(world.countries.geometry)
    stripe = ink.get("stripe")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" '
            f'viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" role="img">'
        ),
        "  <title>Travel footprint</title>",
    ]
    if stripe and layers:
        lines.append("  <defs>")
        lines.append(
            '    <pattern id="christmas-stripes" patternUnits="userSpaceOnUse" '
            'patternContentUnits="userSpaceOnUse" x="0" y="0" '
            f'width="{STRIPE_PERIOD}" height="{STRIPE_PERIOD}">'
        )
        for polygon in _stripe_tile_polygons():
            lines.append(f'      <polygon points="{_points_attr(polygon)}" fill="{stripe}"/>')
        lines.append("    </pattern>")
        combined = " ".join(data for _name, data, _width in layers)
        lines.append('    <clipPath id="visited-clip" clipPathUnits="userSpaceOnUse">')
        lines.append(f'      <path clip-rule="evenodd" d="{combined}"/>')
        lines.append("    </clipPath>")
        lines.append("  </defs>")
    lines.append(
        f'  <rect id="background" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="{chrome["background"]}"/>'
    )
    if land:
        stroke = _num(_points_to_px(LAND_LINEWIDTH))
        lines.append(
            f'  <g id="land" fill="{chrome["land"]}" stroke="{chrome["edge"]}" '
            f'stroke-width="{stroke}" stroke-linejoin="round" stroke-linecap="round" fill-rule="evenodd">'
        )
        lines.append(f'    <path d="{land}"/>')
        lines.append("  </g>")
    if layers:
        if stripe:
            lines.append(f'  <g id="visited" fill="{ink["visited"]}" fill-rule="evenodd">')
            for name, data, _width in layers:
                lines.append(f'    <path data-layer="{name}" d="{data}"/>')
            lines.append("  </g>")
            lines.append('  <g id="stripes" clip-path="url(#visited-clip)">')
            lines.append(
                f'    <rect width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="url(#christmas-stripes)"/>'
            )
            lines.append("  </g>")
            lines.append(
                f'  <g id="visited-edge" fill="none" stroke="{chrome["edge"]}" '
                'stroke-linejoin="round" stroke-linecap="round">'
            )
            for name, data, width in layers:
                lines.append(
                    f'    <path data-layer="{name}" stroke-width="{_num(width)}" d="{data}"/>'
                )
            lines.append("  </g>")
        else:
            lines.append(
                f'  <g id="visited" fill="{ink["visited"]}" stroke="{chrome["edge"]}" '
                'fill-rule="evenodd" stroke-linejoin="round" stroke-linecap="round">'
            )
            for name, data, width in layers:
                lines.append(
                    f'    <path data-layer="{name}" stroke-width="{_num(width)}" d="{data}"/>'
                )
            lines.append("  </g>")
    if resolved.cities:
        halo_r = _num(_marker_radius_px(CITY_HALO_AREA))
        dot_r = _num(_marker_radius_px(CITY_DOT_AREA))
        dot_stroke = _num(_points_to_px(CITY_DOT_LINEWIDTH))
        lines.append('  <g id="cities">')
        for city in resolved.cities:
            x, y = _svg_xy(display_lon(city.lon), city.lat)
            cx, cy = _num(x), _num(y)
            lines.append(
                f'    <circle cx="{cx}" cy="{cy}" r="{halo_r}" fill="{ink["visited"]}" '
                f'fill-opacity="{_num(CITY_HALO_ALPHA)}"/>'
            )
            lines.append(
                f'    <circle cx="{cx}" cy="{cy}" r="{dot_r}" fill="{ink["dot"]}" '
                f'stroke="{ink["visited"]}" stroke-width="{dot_stroke}"/>'
            )
        lines.append("  </g>")
    _append_planned_svg(lines, world, resolved, ink["visited"])
    lines.append("</svg>")
    lines.append("")
    return "\n".join(lines)


def _append_planned_svg(lines: list[str], world: World, resolved: ResolvedTravel, color: str) -> None:
    """Planned states and cities, with SMIL. Absent when the config has none.

    The state group id is ``planned-states``. Each city is ``planned-<name>``.
    Opacity and the city ring run for 1.8s, repeating. The PNG path does not
    call this, so a PNG stays a static fill and dot.
    """
    frame = _subset(world.states, "name", resolved.planned_states)
    data = _path_data(frame.geometry) if not frame.empty else ""
    if data:
        lines.append(
            f'  <g id="planned-states" fill="{color}" fill-rule="evenodd" '
            f'opacity="{_num(PLANNED_FILL_ALPHA)}">'
        )
        lines.append(
            '    <animate attributeName="opacity" '
            f'values="{PLANNED_OPACITY_VALUES}" dur="{PLANNED_DURATION}" '
            'repeatCount="indefinite"/>'
        )
        lines.append(f'    <path d="{data}"/>')
        lines.append("  </g>")
        edge = _num(_points_to_px(PLANNED_EDGE_WIDTH))
        dash = (
            f"{_num(_points_to_px(PLANNED_DASH_ON))} {_num(_points_to_px(PLANNED_DASH_OFF))}"
        )
        lines.append(
            f'  <g id="planned-states-edge" fill="none" stroke="{color}" '
            f'stroke-width="{edge}" stroke-dasharray="{dash}" '
            'stroke-linejoin="round" stroke-linecap="butt">'
        )
        lines.append(f'    <path d="{data}"/>')
        lines.append("  </g>")
    ring = _num(PLANNED_RING_RADIUS)
    ring_end = _num(PLANNED_RING_RADIUS_END)
    dot = _num(PLANNED_DOT_RADIUS)
    stroke = _num(PLANNED_RING_STROKE)
    for city in resolved.planned_cities:
        x, y = _svg_xy(display_lon(city.lon), city.lat)
        cx, cy = _num(x), _num(y)
        lines.append(f'  <g id="{_planned_marker_id(city.name)}">')
        lines.append(
            f'    <circle cx="{cx}" cy="{cy}" r="{ring}" fill="none" '
            f'stroke="{color}" stroke-width="{stroke}">'
        )
        lines.append(
            f'      <animate attributeName="r" values="{ring};{ring_end}" '
            f'dur="{PLANNED_DURATION}" repeatCount="indefinite"/>'
        )
        lines.append(
            f'      <animate attributeName="opacity" values="{PLANNED_RING_OPACITY}" '
            f'dur="{PLANNED_DURATION}" repeatCount="indefinite"/>'
        )
        lines.append("    </circle>")
        lines.append(f'    <circle cx="{cx}" cy="{cy}" r="{dot}" fill="{color}">')
        lines.append(
            f'      <animate attributeName="opacity" values="{PLANNED_DOT_OPACITY}" '
            f'dur="{PLANNED_DURATION}" repeatCount="indefinite"/>'
        )
        lines.append("    </circle>")
        lines.append("  </g>")


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=".travel-map-", suffix=path.suffix, dir=path.parent)
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise DataError(f"could not write {path} ({exc}).") from exc
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def render_png(world: World, resolved: ResolvedTravel, theme: str, palette: str, path: Path) -> None:
    """Write one PNG. ``palette`` must be concrete."""
    background = THEMES[theme]["background"]
    fig = plt.figure(figsize=FIGSIZE, dpi=FIG_DPI, facecolor=background)
    ax = fig.add_axes([0, 0, 1, 1])
    try:
        draw_map(ax, world, resolved, theme, palette)
    except Exception:
        plt.close(fig)
        raise
    _save_figure(fig, path, background)


def render_svg(world: World, resolved: ResolvedTravel, theme: str, palette: str, path: Path) -> None:
    """Write one SVG. ``palette`` must be concrete, not ``auto``.

    The projection, palette, fills, and city dots match ``render_png``. Christmas
    stripes are an SVG pattern: ``#bc4749`` under ``#6a994e`` diagonal bands with
    an 8px period, clipped to the visited shapes. Planned states and cities, when
    present, pulse here with SMIL. The PNG keeps them static.
    """
    if theme not in THEMES:
        raise TravelError(f"unknown theme {theme!r}")
    if palette not in PALETTES:
        raise TravelError(f"unknown palette {palette!r}")
    _write_atomic(path, _svg_document(world, resolved, theme, palette).encode("utf-8"))


# Badge --------------------------------------------------------------------
# A flat shield, the same height as a shields.io badge. Widths are DejaVu Sans
# advances at 11px, in hundredths of a user unit, so the file does not depend
# on the machine that draws it. ``textLength`` locks the glyphs to that width.

BADGE_HEIGHT = 20
BADGE_PADDING = 6
BADGE_LABEL = "visited"
BADGE_FONT_FAMILY = "DejaVu Sans, Verdana, Geneva, sans-serif"
_BADGE_ADVANCE_DEFAULT = 700
_BADGE_ADVANCE = {
    " ": 350,
    "%": 1050,
    ".": 338,
    "-": 400,
    "·": 338,
    "0": 700,
    "1": 700,
    "2": 688,
    "3": 700,
    "4": 688,
    "5": 688,
    "6": 700,
    "7": 700,
    "8": 700,
    "9": 700,
    "A": 750,
    "B": 750,
    "C": 762,
    "D": 850,
    "E": 700,
    "F": 638,
    "G": 850,
    "H": 838,
    "I": 325,
    "J": 325,
    "K": 725,
    "L": 612,
    "M": 950,
    "N": 825,
    "O": 862,
    "P": 662,
    "Q": 862,
    "R": 762,
    "S": 700,
    "T": 675,
    "U": 812,
    "V": 750,
    "W": 1088,
    "X": 750,
    "Y": 675,
    "Z": 750,
    "a": 675,
    "b": 700,
    "c": 612,
    "d": 700,
    "e": 688,
    "f": 400,
    "g": 700,
    "h": 700,
    "i": 312,
    "j": 312,
    "k": 638,
    "l": 312,
    "m": 1075,
    "n": 700,
    "o": 675,
    "p": 700,
    "q": 700,
    "r": 462,
    "s": 575,
    "t": 438,
    "u": 688,
    "v": 650,
    "w": 900,
    "x": 650,
    "y": 650,
    "z": 575,
}


def world_country_total(world: World) -> int:
    """How many countries the map can draw. Antarctica is already excluded."""
    total = int(world.countries["adm0_a3"].nunique())
    if total <= 0:
        raise TravelError("the map has no countries to compare against.")
    return total


def travel_stats(resolved: ResolvedTravel, world: World) -> TravelStats:
    """Counts of the visited places ``resolved`` draws.

    Planned states and planned cities are drawn on the map and left out of
    every count here. A config that adds only those keys keeps the same stats.
    """
    return TravelStats(
        countries=len(resolved.countries),
        world_countries=world_country_total(world),
        us_states=len(resolved.states),
        china_provinces=len(resolved.provinces),
        japan_prefectures=len(resolved.prefectures),
    )


def percent_of_world(countries: int, world_countries: int) -> str:
    """``countries / world_countries`` as a percent, to the nearest tenth.

    A whole number drops the decimal, so ``0%`` and ``100%`` stay whole.
    Half a tenth rounds up.
    """
    if type(countries) is not int or countries < 0:
        raise TravelError(f"country count is {countries!r}, which is not a count.")
    if type(world_countries) is not int or world_countries <= 0:
        raise TravelError("the map has no countries to compare against.")
    tenths = (1000 * countries + world_countries // 2) // world_countries
    whole, frac = divmod(tenths, 10)
    if frac == 0:
        return f"{whole}%"
    return f"{whole}.{frac}%"


def _count_phrase(count: int, singular: str, plural: str) -> str:
    noun = singular if count == 1 else plural
    return f"{count} {noun}"


def _check_stats(stats: TravelStats) -> None:
    fields = (
        ("countries", stats.countries),
        ("world_countries", stats.world_countries),
        ("us_states", stats.us_states),
        ("china_provinces", stats.china_provinces),
        ("japan_prefectures", stats.japan_prefectures),
    )
    for name, value in fields:
        if type(value) is not int or value < 0:
            raise TravelError(f"{name} count is {value!r}, which is not a count.")
    if stats.world_countries == 0:
        raise TravelError("the map has no countries to compare against.")


def badge_parts(stats: TravelStats) -> tuple[str, ...]:
    """The visible badge phrases, in order.

    China and Japan are included only when those units are drawn. US states
    stay even at zero, so a country-only map still shows that count.
    """
    _check_stats(stats)
    parts = [
        _count_phrase(stats.countries, "country", "countries"),
        f"{percent_of_world(stats.countries, stats.world_countries)} of world",
        _count_phrase(stats.us_states, "US state", "US states"),
    ]
    if stats.china_provinces:
        parts.append(_count_phrase(stats.china_provinces, "China province", "China provinces"))
    if stats.japan_prefectures:
        parts.append(_count_phrase(stats.japan_prefectures, "Japan prefecture", "Japan prefectures"))
    return tuple(parts)


def badge_message(stats: TravelStats) -> str:
    """The single line drawn on the badge."""
    return " · ".join(badge_parts(stats))


def badge_title(stats: TravelStats) -> str:
    """Accessible name. The percent names the country total it was divided by."""
    parts = list(badge_parts(stats))
    percent = percent_of_world(stats.countries, stats.world_countries)
    parts[1] = f"{percent} of {stats.world_countries} world countries"
    return "Travel footprint: " + ", ".join(parts)


def _xml_text(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _xml_attr(text: str) -> str:
    return _xml_text(text).replace('"', "&quot;")


def _advance(text: str) -> int:
    """Text width in hundredths of an SVG user unit."""
    return sum(_BADGE_ADVANCE.get(char, _BADGE_ADVANCE_DEFAULT) for char in text)


def _segment_width(advance: int) -> int:
    """Pixel width of one badge segment, including horizontal padding."""
    return (advance + 2 * BADGE_PADDING * 100 + 99) // 100


def badge_colors(palette: str) -> dict[str, str]:
    """Shield colors for a concrete palette.

    The value side uses that palette's dark-theme visited color. The badge
    has its own background, so it does not switch with the light map. Default
    and Halloween put white text on the visited color. Halloween keeps the
    yellow dot color on the dark label. Christmas uses the red fill, the
    green stripe, and the cream dot.
    """
    if palette not in PALETTES:
        raise TravelError(f"unknown palette {palette!r}")
    ink = PALETTES[palette]["dark"]
    if palette == "christmas":
        return {
            "label_bg": ink["stripe"],
            "label_fg": ink["dot"],
            "value_bg": ink["visited"],
            "value_fg": ink["dot"],
        }
    if palette == "halloween":
        return {
            "label_bg": THEMES["dark"]["background"],
            "label_fg": ink["dot"],
            "value_bg": ink["visited"],
            "value_fg": "#ffffff",
        }
    return {
        "label_bg": THEMES["dark"]["background"],
        "label_fg": "#ffffff",
        "value_bg": ink["visited"],
        "value_fg": ink["dot"],
    }


def _badge_text(x: float, y: int, fill: str, advance: int, content: str, part: str, *, shadow: bool) -> str:
    opacity = ' fill-opacity="0.3"' if shadow else ""
    return (
        f'    <text data-part="{part}" x="{_num(x)}" y="{y}" fill="{fill}"{opacity} '
        f'textLength="{_num(advance / 100)}" lengthAdjust="spacing">{_xml_text(content)}</text>'
    )


def badge_document(stats: TravelStats, palette: str) -> str:
    """One self-contained shield. No images, fonts, or network URLs."""
    colors = badge_colors(palette)
    message = badge_message(stats)
    title = badge_title(stats)
    label_advance = _advance(BADGE_LABEL)
    value_advance = _advance(message)
    label_width = _segment_width(label_advance)
    value_width = _segment_width(value_advance)
    total = label_width + value_width
    label_x = label_width / 2
    value_x = label_width + value_width / 2
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{total}" height="{BADGE_HEIGHT}" '
            f'viewBox="0 0 {total} {BADGE_HEIGHT}" role="img" aria-label="{_xml_attr(title)}">'
        ),
        f"  <title>{_xml_text(title)}</title>",
        "  <defs>",
        '    <linearGradient id="travel-badge-shine" x2="0" y2="100%">',
        '      <stop offset="0" stop-color="#ffffff" stop-opacity="0.1"/>',
        '      <stop offset="1" stop-color="#ffffff" stop-opacity="0.1"/>',
        "    </linearGradient>",
        '    <clipPath id="travel-badge-round">',
        f'      <rect width="{total}" height="{BADGE_HEIGHT}" rx="3"/>',
        "    </clipPath>",
        "  </defs>",
        '  <g clip-path="url(#travel-badge-round)">',
        (
            f'    <rect data-part="label-bg" width="{label_width}" height="{BADGE_HEIGHT}" '
            f'fill="{colors["label_bg"]}"/>'
        ),
        (
            f'    <rect data-part="value-bg" x="{label_width}" width="{value_width}" '
            f'height="{BADGE_HEIGHT}" fill="{colors["value_bg"]}"/>'
        ),
        (
            f'    <rect data-part="shine" width="{total}" height="{BADGE_HEIGHT}" '
            'fill="url(#travel-badge-shine)"/>'
        ),
        "  </g>",
        (
            f'  <g aria-hidden="true" text-anchor="middle" font-family="{BADGE_FONT_FAMILY}" '
            f'font-size="11">'
        ),
        _badge_text(label_x, 15, "#010101", label_advance, BADGE_LABEL, "label-shadow", shadow=True),
        _badge_text(label_x, 14, colors["label_fg"], label_advance, BADGE_LABEL, "label", shadow=False),
        _badge_text(value_x, 15, "#010101", value_advance, message, "value-shadow", shadow=True),
        _badge_text(value_x, 14, colors["value_fg"], value_advance, message, "value", shadow=False),
        "  </g>",
        "</svg>",
        "",
    ]
    return "\n".join(lines)


def render_badge(stats: TravelStats, palette: str, path: Path) -> None:
    """Write ``travel-badge.svg``. ``palette`` must be concrete, not ``auto``."""
    if palette not in PALETTES:
        raise TravelError(f"unknown palette {palette!r}")
    _write_atomic(path, badge_document(stats, palette).encode("utf-8"))


def render_maps(
    config: TravelConfig,
    out_dir: Path,
    palette: str,
    today: date,
    *,
    world: World | None = None,
    image_format: str = "png",
    badge: bool = True,
) -> RenderResult:
    """Resolve ``config`` and write the requested maps. Nothing is written on failure.

    ``image_format`` is ``png`` (the default), ``svg``, or ``both``. ``png`` writes
    the dark and light PNGs. ``svg`` writes the dark and light SVGs. ``both`` writes
    all four. The default keeps the PNG-only behavior.

    ``badge`` writes ``travel-badge.svg`` beside those files when true, which is
    the default. False writes no badge and does not change the map files. The
    badge counts visited countries, the percent of world countries the map can
    draw, and visited US states. China provinces and Japan prefectures are
    included when those units are drawn. Planned states and planned cities are
    not included. Colors follow the concrete palette.
    """
    image_format = parse_format(image_format)
    if type(badge) is not bool:
        raise InputError(
            f"badge is {badge!r}, which is not true or false. "
            "Use true to write travel-badge.svg next to the map, or false to skip it."
        )
    if out_dir.exists() and not out_dir.is_dir():
        raise InputError(
            f"output (--out) is {str(out_dir)!r}, which is a file. Pass a directory, for example dist."
        )
    concrete = resolve_palette(palette, today)
    world = load_world() if world is None else world
    resolved = resolve_travel(config, world)
    out_dir.mkdir(parents=True, exist_ok=True)
    dark = out_dir / DARK_FILENAME
    light = out_dir / LIGHT_FILENAME
    dark_svg = out_dir / DARK_SVG_FILENAME
    light_svg = out_dir / LIGHT_SVG_FILENAME
    badge_path = out_dir / BADGE_FILENAME
    want_png = image_format in {"png", "both"}
    want_svg = image_format in {"svg", "both"}
    written: list[Path] = []
    try:
        if want_png:
            render_png(world, resolved, "dark", concrete, dark)
            written.append(dark)
            render_png(world, resolved, "light", concrete, light)
            written.append(light)
        if want_svg:
            render_svg(world, resolved, "dark", concrete, dark_svg)
            written.append(dark_svg)
            render_svg(world, resolved, "light", concrete, light_svg)
            written.append(light_svg)
        if badge:
            render_badge(travel_stats(resolved, world), concrete, badge_path)
            written.append(badge_path)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return RenderResult(
        dark_path=dark if want_png else None,
        light_path=light if want_png else None,
        palette=concrete,
        resolved=resolved,
        dark_svg_path=dark_svg if want_svg else None,
        light_svg_path=light_svg if want_svg else None,
        badge_path=badge_path if badge else None,
    )
