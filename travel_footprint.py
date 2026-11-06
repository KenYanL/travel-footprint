#!/usr/bin/env python3
"""Checkout entry point used by the composite action.

``action.yml`` runs this file with the same flags as before. ``pip install .``
provides the ``travel-footprint`` command. The package is not published on PyPI.
"""

from __future__ import annotations

import sys

from travel_footprint import main

if __name__ == "__main__":
    sys.exit(main())
