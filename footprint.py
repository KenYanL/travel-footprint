"""Checkout shim so ``import footprint`` keeps working.

The implementation and the Natural Earth files live in the
``travel_footprint`` package. This file is not installed. ``pip install .``
provides ``travel-footprint`` and imports ``travel_footprint.footprint``.
"""

from __future__ import annotations

import sys

from travel_footprint import footprint as _impl

sys.modules[__name__] = _impl
