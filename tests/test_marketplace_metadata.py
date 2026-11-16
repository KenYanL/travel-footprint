"""GitHub Marketplace rejects metadata that misses these rules."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_action_metadata_meets_marketplace_rules() -> None:
    data = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    assert data["name"] == "Travel Footprint"
    assert data["author"] == "KenYanL"
    description = data["description"]
    assert isinstance(description, str) and description
    assert len(description) < 125
    assert data["branding"]["icon"] == "map"
    assert data["branding"]["color"] == "green"
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 KenYanL" in license_text
    assert "MIT License" in license_text
