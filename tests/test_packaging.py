"""The checkout import path still finds vendored Natural Earth files."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import footprint
from footprint import DATASET_NAMES, VENDOR_DIR
from travel_footprint import main

ROOT = Path(__file__).resolve().parents[1]


def test_import_footprint_finds_packaged_natural_earth_files() -> None:
    impl = Path(footprint.__file__).resolve()
    assert impl == (ROOT / "travel_footprint" / "footprint.py").resolve()
    assert VENDOR_DIR == impl.parent / "data"
    assert (VENDOR_DIR / "SHA256SUMS").is_file()
    assert (VENDOR_DIR / "README.md").is_file()
    for name in DATASET_NAMES:
        assert (VENDOR_DIR / name).is_file()


def test_pyproject_declares_the_distribution() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "travel-footprint"' in text
    assert 'version = "0.1.0"' in text
    assert 'requires-python = ">=3.10"' in text
    assert 'license = "MIT"' in text
    assert 'travel-footprint = "travel_footprint:main"' in text
    for pin in (
        "geopandas==1.1.1",
        "matplotlib==3.10.7",
        "PyYAML==6.0.3",
        "shapely==2.2.0",
    ):
        assert pin in text
    assert "twine upload" not in text


def test_checkout_help_keeps_the_script_name(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["travel_footprint.py", "--help"])
    with pytest.raises(SystemExit) as caught:
        main(None)
    assert caught.value.code == 0
    out = capsys.readouterr().out
    assert "usage: travel_footprint.py" in out
    assert "Pacific-centred" in out


def test_console_script_help_uses_the_command_name(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["travel-footprint", "--help"])
    with pytest.raises(SystemExit) as caught:
        main(None)
    assert caught.value.code == 0
    assert "usage: travel-footprint" in capsys.readouterr().out
