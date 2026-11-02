"""Load a travel file and draw a Pacific-centred world map.

Countries, US states, and cities come from the caller's YAML file. Coastlines
come from the Natural Earth extracts under ``data/`` (see ``data/README.md``).
The map is plate carrée, seam at 30°W, so the Pacific sits in the middle and
the Americas sit on the right.
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
import yaml
from shapely.affinity import translate
from shapely.geometry import box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent
VENDOR_DIR = ROOT / "data"

COUNTRIES_ZIP = "ne_50m_admin_0_countries.zip"
STATES_ZIP = "ne_50m_admin_1_states_provinces.zip"
DATASET_NAMES = (COUNTRIES_ZIP, STATES_ZIP)
DATASET_URLS = {
    COUNTRIES_ZIP: "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_0_countries.zip",
    STATES_ZIP: "https://naciscdn.org/naturalearth/50m/cultural/ne_50m_admin_1_states_provinces.zip",
}

DARK_FILENAME = "travel-map.png"
LIGHT_FILENAME = "travel-map-light.png"

# Pacific-centred plate carrée. Seam at 30°W (central meridian 150°E).
# Land west of the seam is shifted by +360 so the Americas sit on the right.
SEAM = -30.0
MAP_XLIM = (SEAM, SEAM + 360.0)
MAP_YLIM = (-58.0, 84.0)
_WEST = box(-180.0, -90.0, SEAM, 90.0)
_EAST = box(SEAM, -90.0, 180.0, 90.0)

# Figure size matches a 360° by 142° frame, so the map fills the PNG.
FIGSIZE = (12.0, 4.74)
FIG_DPI = 100

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

# ``visited`` fills a whole country or a highlighted state.
# ``tier`` fills a country when only some of its states are listed.
# ``dot`` is the city marker. Dark values for halloween and christmas are the
# ones named in the action contract. Light values are the readable equivalents
# on a white background (darker city dots, because cream and yellow vanish).
PALETTES: dict[str, dict[str, dict[str, str]]] = {
    "default": {
        "dark": {"visited": "#3fb950", "tier": "#1f6f35", "dot": "#ffffff"},
        "light": {"visited": "#1a7f37", "tier": "#4ac26b", "dot": "#1f2328"},
    },
    "halloween": {
        # Dark orange, burnt orange, and yellow from GitHub Primer
        # @primer/primitives 11.10.0, dark --contribution-halloween-bgColor.
        "dark": {"visited": "#c46212", "tier": "#984b10", "dot": "#e3d04f"},
        "light": {"visited": "#c46212", "tier": "#f68c41", "dot": "#1f2328"},
    },
    "christmas": {
        # Coolors' most popular Christmas palette
        # https://coolors.co/palettes/popular/christmas
        # 386641, 6a994e, a7c957, f2e8cf, bc4749.
        "dark": {"visited": "#bc4749", "tier": "#386641", "dot": "#f2e8cf"},
        "light": {"visited": "#bc4749", "tier": "#6a994e", "dot": "#1f2328"},
    },
}

PALETTE_NAMES = ("default", "halloween", "christmas", "auto")

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
    path: str | None = None

    @property
    def label(self) -> str:
        return self.path or "config"


@dataclass(frozen=True)
class ResolvedTravel:
    """Places matched to Natural Earth ids. ``states`` is what gets painted."""

    countries: tuple[str, ...]
    tier_countries: tuple[str, ...]
    states: tuple[str, ...]
    cities: tuple[City, ...]
    note: str | None = None


@dataclass
class World:
    countries: object
    states: object
    country_index: dict[str, str | None]
    state_index: dict[str, str | None]
    country_names: tuple[str, ...]
    state_names: tuple[str, ...]


@dataclass(frozen=True)
class RenderResult:
    dark_path: Path
    light_path: Path
    palette: str
    resolved: ResolvedTravel


def normalize_name(value: str) -> str:
    """Fold case, accents, and punctuation so ``Côte d'Ivoire`` matches a typed name."""
    text = unicodedata.normalize("NFKD", value)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


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
    if name not in DATASET_URLS:
        raise DataError(f"unknown map dataset {name!r}.")
    vendor_root = VENDOR_DIR if vendor_dir is None else vendor_dir
    vendored = vendor_root / name
    cached_root = cache_directory() if cache_dir is None else cache_dir
    cached = cached_root / name
    path = vendored if vendored.is_file() else cached
    if not path.is_file():
        cached_root.mkdir(parents=True, exist_ok=True)
        fetch(DATASET_URLS[name], cached)
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


@lru_cache(maxsize=1)
def read_admin1_usa():
    """Unprojected US states and the District of Columbia."""
    frame = _open_zip(STATES_ZIP)
    needed = ["adm0_a3", "name", "postal", "iso_3166_2", "type_en", "geometry"]
    missing = [column for column in needed if column not in frame.columns]
    if missing:
        raise DataError(
            f"{STATES_ZIP} is missing {', '.join(missing)}. "
            "travel-footprint expects the Natural Earth admin-1 fields."
        )
    columns = needed + [column for column in ("name_en", "name_alt") if column in frame.columns]
    frame = frame.loc[:, columns].copy()
    frame = frame[frame["adm0_a3"].map(_text) == "USA"]
    if "type_en" in frame.columns:
        frame = frame[frame["type_en"].isin(["State", "Federal District"])]
    geometry = frame.geometry
    frame = frame[geometry.notna() & ~geometry.is_empty].copy()
    frame["name"] = frame["name"].map(lambda value: str(value).strip())
    if frame.empty:
        raise DataError(f"{STATES_ZIP} has no US states to highlight.")
    return frame


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


def build_state_index(frame) -> tuple[dict[str, str | None], tuple[str, ...]]:
    index: dict[str, str | None] = {}
    displays: set[str] = set()
    for row in frame.itertuples(index=False):
        canonical = str(row.name).strip()
        _add_label(index, canonical, canonical)
        displays.add(canonical)
        for field in ("name_en", "name_alt", "postal", "iso_3166_2"):
            if hasattr(row, field):
                _add_label(index, getattr(row, field), canonical)
    for alias, canonical in STATE_ALIASES.items():
        if canonical in displays:
            _add_label(index, alias, canonical)
    return index, tuple(sorted(displays))


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
    country_index, country_names = build_country_index(countries)
    state_index, state_names = build_state_index(states)
    return World(
        countries=project_frame(countries, 0.08),
        states=project_frame(states, 0.01),
        country_index=country_index,
        state_index=state_index,
        country_names=country_names,
        state_names=state_names,
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

_ALLOWED_KEYS = ("countries", "us_states", "cities")
_CITY_KEYS = {"name", "lat", "latitude", "lon", "lng", "long", "longitude"}


def _yaml_error_text(exc: yaml.YAMLError) -> str:
    text = str(exc).strip().splitlines()
    return text[0] if text else "the file could not be parsed"


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
            "Use a mapping with countries, us_states, and cities."
        ) from exc
    if data is None:
        raise ConfigError(
            f"{where} is empty. List countries, us_states, and cities. "
            "See travel.example.yml."
        )
    if not isinstance(data, dict):
        raise ConfigError(
            f"{where} must be a YAML mapping of countries, us_states, and cities, "
            f"not {type(data).__name__}."
        )
    unknown = [key for key in data if key not in _ALLOWED_KEYS]
    if unknown:
        noun = "key" if len(unknown) == 1 else "keys"
        names = ", ".join(repr(key) for key in unknown)
        raise ConfigError(
            f"{where} has unknown {noun} {names}. "
            "Supported keys are countries, us_states, and cities. "
            "Other subdivisions are not supported yet."
        )
    return TravelConfig(
        countries=_string_list(_section(data, "countries", where), "countries", where),
        us_states=_string_list(_section(data, "us_states", where), "us_states", where),
        cities=_cities(_section(data, "cities", where), where),
        path=path,
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
            "Pass a YAML file of countries, us_states, and cities, for example travel.yml."
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"config {path} could not be read ({exc}).") from exc
    return parse_config(text, path=str(path))


def _string_list(value: object, field: str, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    example = (
        "Use a list of ISO 3166-1 alpha-2 or alpha-3 codes or English names, for example [NZ, Japan]."
        if field == "countries"
        else "Use a list of US state names or USPS codes, for example [Colorado, ME]."
    )
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


def _cities(value: object, where: str) -> tuple[City, ...]:
    if value is None:
        return ()
    example = (
        "Each city needs a name, lat (or latitude) from -90 to 90, "
        "and lon (or longitude) from -180 to 180."
    )
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ConfigError(f"{where}: cities is {value!r}, which is not a list. {example}")
    cities: list[City] = []
    for index, item in enumerate(value, start=1):
        cities.append(_one_city(item, index, where, example))
    return tuple(cities)


def _one_city(item: object, index: int, where: str, example: str) -> City:
    label = f"{where}: cities entry {index}"
    if not isinstance(item, dict):
        raise ConfigError(f"{label} is {item!r}, which is not a mapping. {example}")
    unknown = [key for key in item if key not in _CITY_KEYS]
    if unknown:
        names = ", ".join(repr(key) for key in unknown)
        raise ConfigError(f"{label} has unknown key {names}. {example}")
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


def resolve_travel(config: TravelConfig, world: World | None = None) -> ResolvedTravel:
    """Match config entries to Natural Earth ids."""
    world = load_world() if world is None else world
    where = config.label
    country_example = (
        "Use an ISO 3166-1 alpha-2 or alpha-3 code or an English name, for example NZ or New Zealand."
    )
    state_example = "Use a state name or USPS code, for example Wyoming or WY."
    countries: list[str] = []
    seen_countries: dict[str, str] = {}
    for entry in config.countries:
        code = resolve_token(
            entry,
            world.country_index,
            world.country_names,
            field=f"{where}: countries",
            example=country_example,
        )
        if code in seen_countries:
            raise ConfigError(
                f"{where}: countries entry {entry!r} is the same country as "
                f"{seen_countries[code]!r}. List it once."
            )
        seen_countries[code] = entry
        countries.append(code)

    states: list[str] = []
    seen_states: dict[str, str] = {}
    for entry in config.us_states:
        canonical = resolve_token(
            entry,
            world.state_index,
            world.state_names,
            field=f"{where}: us_states",
            example=state_example,
        )
        if canonical in seen_states:
            raise ConfigError(
                f"{where}: us_states entry {entry!r} is the same state as "
                f"{seen_states[canonical]!r}. List it once."
            )
        seen_states[canonical] = entry
        states.append(canonical)

    note = None
    painted_states: tuple[str, ...] = tuple(states)
    tier: list[str] = []
    if states:
        if "USA" in countries:
            painted_states = ()
            note = (
                "USA is listed under countries, so the whole country is filled "
                "and us_states are not drawn separately."
            )
        else:
            tier.append("USA")
    return ResolvedTravel(
        countries=tuple(countries),
        tier_countries=tuple(tier),
        states=painted_states,
        cities=config.cities,
        note=note,
    )


# Drawing ------------------------------------------------------------------

def _paint(ax, frame, column: str, keys: tuple[str, ...], color: str, edge: str, width: float, zorder: int) -> None:
    if not keys:
        return
    part = frame[frame[column].isin(keys)]
    if part.empty:
        return
    part.plot(ax=ax, color=color, edgecolor=edge, linewidth=width, zorder=zorder)


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
    _paint(ax, countries, "adm0_a3", tuple(countries["adm0_a3"]), chrome["land"], chrome["edge"], 0.3, 1)
    _paint(ax, countries, "adm0_a3", resolved.tier_countries, ink["tier"], chrome["edge"], 0.3, 2)
    _paint(ax, world.states, "name", resolved.states, ink["visited"], chrome["edge"], 0.18, 3)
    _paint(ax, countries, "adm0_a3", resolved.countries, ink["visited"], chrome["edge"], 0.3, 4)
    if resolved.cities:
        xs = [city.lon + 360.0 if city.lon < SEAM else city.lon for city in resolved.cities]
        ys = [city.lat for city in resolved.cities]
        ax.scatter(xs, ys, s=35, color=ink["visited"], alpha=0.25, zorder=5, linewidths=0)
        ax.scatter(
            xs,
            ys,
            s=10,
            color=ink["dot"],
            edgecolor=ink["visited"],
            linewidths=0.8,
            zorder=6,
        )
    ax.set_xlim(*MAP_XLIM)
    ax.set_ylim(*MAP_YLIM)
    ax.set_aspect("equal", adjustable="datalim")
    ax.axis("off")


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


def render_maps(
    config: TravelConfig,
    out_dir: Path,
    palette: str,
    today: date,
    *,
    world: World | None = None,
) -> RenderResult:
    """Resolve ``config`` and write the dark and light PNGs. Nothing is written on failure."""
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
    render_png(world, resolved, "dark", concrete, dark)
    try:
        render_png(world, resolved, "light", concrete, light)
    except Exception:
        dark.unlink(missing_ok=True)
        raise
    return RenderResult(dark_path=dark, light_path=light, palette=concrete, resolved=resolved)
