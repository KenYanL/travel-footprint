"""Pacific-centred travel map.

The console script ``travel-footprint`` calls :func:`main`. Map drawing lives
in :mod:`travel_footprint.footprint`, with Natural Earth files in ``data/``
next to that module.
"""

from __future__ import annotations

__all__ = ["main"]


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Heavy imports wait until a map is actually drawn."""
    from .cli import main as cli_main

    return cli_main(argv)
