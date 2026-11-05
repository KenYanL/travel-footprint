#!/usr/bin/env python3
"""Render a travel-footprint world map.

Writes a dark map and a light map from a YAML file of countries, US states,
Chinese provinces, Japanese prefectures, and cities. The default format is
PNG (``travel-map.png`` and ``travel-map-light.png``). ``--format svg`` writes
the same maps as SVG, and ``--format both`` writes all four files.

Examples:
  python3 travel_footprint.py --config travel.yml --out dist/ --palette default
  python3 travel_footprint.py --config travel.yml --out dist/ --palette auto
  python3 travel_footprint.py --config travel.yml --out dist/ --palette auto --date 2026-12-25
  python3 travel_footprint.py --config travel.yml --out dist/ --format both
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="travel_footprint.py",
        description=(
            "Render a Pacific-centred world map of visited countries, US states, "
            "Chinese provinces, Japanese prefectures, and cities. "
            "Writes a dark map and a light map. The default format is PNG."
        ),
    )
    parser.add_argument(
        "--config",
        default="travel.yml",
        help=(
            "YAML file of countries, us_states, china_provinces, japan_prefectures, "
            "cities, planned, and planned_states. Default: travel.yml."
        ),
    )
    parser.add_argument(
        "--out",
        default="dist",
        help="Directory for the map files. Default: dist.",
    )
    parser.add_argument(
        "--palette",
        default="default",
        help="default, halloween, christmas, or auto. Default: default.",
    )
    parser.add_argument(
        "--format",
        default="png",
        help="png, svg, or both. png is the default and writes only the two PNGs.",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="UTC calendar day used when palette is auto, as YYYY-MM-DD. Default: today (UTC).",
    )
    return parser.parse_args(argv)


def _check_text(raw: object, flag: str, example: str) -> str:
    from footprint import InputError

    if not isinstance(raw, str) or raw.strip() == "" or raw != raw.strip():
        shown = "empty" if isinstance(raw, str) and raw.strip() == "" else repr(raw)
        raise InputError(
            f"{flag} is {shown}. Pass {example}."
        )
    if any(ord(char) < 32 or ord(char) == 127 for char in raw):
        raise InputError(f"{flag} is {raw!r}, which contains a control character. Pass {example}.")
    return raw


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        from footprint import (
            InputError,
            TravelError,
            load_config,
            parse_date,
            parse_format,
            parse_palette,
            render_maps,
        )
    except ImportError:
        print(
            "travel-footprint: missing dependencies. "
            "Install them with python3 -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    try:
        config_arg = _check_text(args.config, "config (--config)", "a YAML path, for example travel.yml")
        out_arg = _check_text(args.out, "output (--out)", "a directory, for example dist")
        palette = parse_palette(args.palette)
        image_format = parse_format(args.format)
        today = parse_date(args.date) if args.date is not None else datetime.now(timezone.utc).date()
        config = load_config(Path(config_arg))
        result = render_maps(config, Path(out_arg), palette, today, image_format=image_format)
    except TravelError as exc:
        print(f"travel-footprint: {exc}", file=sys.stderr)
        return 1

    if result.resolved.note:
        print(f"travel-footprint: {result.resolved.note}", file=sys.stderr)
    print(f"palette {result.palette}")
    for written in (result.dark_path, result.light_path, result.dark_svg_path, result.light_svg_path):
        if written is not None:
            print(f"wrote {written}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
