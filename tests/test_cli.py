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
    assert not (out / "travel-map.svg").exists()
    assert not (out / "travel-map-light.svg").exists()


def test_format_svg_writes_svg_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "travel.yml"
    config.write_text("countries:\n  - NZ\n", encoding="utf-8")
    out = tmp_path / "dist"
    code = main(["--config", str(config), "--out", str(out), "--format", "svg"])
    assert code == 0
    captured = capsys.readouterr()
    assert "palette default" in captured.out
    assert (out / "travel-map.svg").is_file()
    assert (out / "travel-map-light.svg").is_file()
    assert not (out / "travel-map.png").exists()
    assert not (out / "travel-map-light.png").exists()
    assert str(out / "travel-map.svg") in captured.out


def test_format_both_writes_png_and_svg(tmp_path: Path) -> None:
    config = tmp_path / "travel.yml"
    config.write_text(
        "countries:\n  - NZ\ncities:\n  - name: Site A\n    lat: -41.0\n    lon: 174.0\n",
        encoding="utf-8",
    )
    out = tmp_path / "dist"
    code = main(["--config", str(config), "--out", str(out), "--format", " Both "])
    assert code == 0
    for name in (
        "travel-map.png",
        "travel-map-light.png",
        "travel-map.svg",
        "travel-map-light.svg",
    ):
        assert (out / name).is_file(), name


def test_unknown_format_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "travel.yml"
    config.write_text("countries:\n  - NZ\n", encoding="utf-8")
    out = tmp_path / "dist"
    code = main(["--config", str(config), "--out", str(out), "--format", "gif"])
    assert code == 1
    assert not out.exists()
    captured = capsys.readouterr()
    assert "gif" in captured.err
    assert "svg" in captured.err
    assert "both" in captured.err


def test_action_yml_exposes_config_output_and_palette() -> None:
    import yaml

    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert data["runs"]["using"] == "composite"
    assert set(data["inputs"]) == {"config", "output", "palette", "format", "badge"}
    assert data["inputs"]["config"]["default"] == "travel.yml"
    assert data["inputs"]["output"]["default"] == "dist"
    assert data["inputs"]["palette"]["default"] == "default"
    assert data["inputs"]["format"]["default"] == "png"
    assert data["inputs"]["badge"]["default"] == "true"
    assert "false" in data["inputs"]["badge"]["description"]
    assert "travel-badge.svg" in data["inputs"]["badge"]["description"]
    assert "svg" in data["inputs"]["format"]["description"]
    assert "both" in data["inputs"]["format"]["description"]
    assert "travel_footprint.py" in text
    assert '--palette "${TRAVEL_PALETTE-default}"' in text
    assert '--format "${TRAVEL_FORMAT-png}"' in text
    assert '--badge "${TRAVEL_BADGE-true}"' in text
    assert "TRAVEL_BADGE: ${{ inputs.badge }}" in text
    assert "requirements.txt" in text
    outputs = data["outputs"]
    assert set(outputs) == {
        "map_dark_path",
        "map_light_path",
        "map_dark_svg_path",
        "map_light_svg_path",
        "badge_path",
    }
    assert outputs["map_dark_svg_path"]["value"] == "${{ steps.render.outputs.map_dark_svg_path }}"
    assert outputs["badge_path"]["value"] == "${{ steps.render.outputs.badge_path }}"
    assert "travel-map.svg" in text
    assert "travel-map-light.svg" in text
    assert "travel-badge.svg" in text


def test_workflow_runs_pytest_on_pull_requests() -> None:
    text = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "pull_request" in text
    assert "pytest" in text
    assert "python -m build" in text
    assert "twine check" in text
