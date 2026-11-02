"""CLI failures and the composite action wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from travel_footprint import main

ROOT = Path(__file__).resolve().parents[1]


def test_unknown_palette_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "travel.yml"
    config.write_text("countries:\n  - NZ\n", encoding="utf-8")
    out = tmp_path / "dist"
    code = main(["--config", str(config), "--out", str(out), "--palette", "neon"])
    assert code == 1
    assert not out.exists()
    captured = capsys.readouterr()
    assert "neon" in captured.err
    assert "travel-footprint:" in captured.err


def test_bad_date_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "travel.yml"
    config.write_text("{}\n", encoding="utf-8")
    code = main(["--config", str(config), "--out", str(tmp_path / "dist"), "--date", "2026-13-01"])
    assert code == 1
    assert "YYYY-MM-DD" in capsys.readouterr().err


def test_missing_config_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--config", str(tmp_path / "missing.yml"), "--out", str(tmp_path / "dist")])
    assert code == 1
    assert "does not exist" in capsys.readouterr().err


def test_cli_renders_the_example(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "dist"
    code = main(
        [
            "--config",
            str(ROOT / "travel.example.yml"),
            "--out",
            str(out),
            "--palette",
            "auto",
            "--date",
            "2026-10-31",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "palette halloween" in captured.out
    assert (out / "travel-map.png").is_file()
    assert (out / "travel-map-light.png").is_file()


def test_action_yml_exposes_config_output_and_palette() -> None:
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert "using: composite" in text
    for name in ("config:", "output:", "palette:"):
        assert name in text
    assert "default: travel.yml" in text
    assert "default: dist" in text
    assert "default: default" in text
    assert "travel_footprint.py" in text
    assert '--palette "${TRAVEL_PALETTE-default}"' in text
    assert "requirements.txt" in text
    assert "map_dark_path" in text
    assert "map_light_path" in text


def test_workflow_runs_pytest_on_pull_requests() -> None:
    text = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "pull_request" in text
    assert "pytest" in text
