"""Tests for microchip_devtools.format.uncrustify."""

from pathlib import Path
from unittest.mock import patch

from microchip_devtools.format.uncrustify import (
    DEFAULT_CONFIG,
    _collect_files,
    format_files,
)


# --- Bundled config -----------------------------------------------------------

def test_default_config_is_path():
    assert isinstance(DEFAULT_CONFIG, Path)


def test_default_config_exists():
    assert DEFAULT_CONFIG.exists(), f"Bundled config not found: {DEFAULT_CONFIG}"


def test_default_config_is_inside_package():
    assert "microchip_devtools" in str(DEFAULT_CONFIG)


# --- _collect_files -----------------------------------------------------------

def test_collect_files_finds_c_and_h(tmp_path):
    (tmp_path / "main.c").write_text("")
    (tmp_path / "main.h").write_text("")
    (tmp_path / "readme.md").write_text("")
    found = _collect_files([tmp_path], [".c", ".h"], [])
    assert {f.name for f in found} == {"main.c", "main.h"}


def test_collect_files_excludes_pattern(tmp_path):
    (tmp_path / "main.c").write_text("")
    (tmp_path / "mcc_main.c").write_text("")
    found = _collect_files([tmp_path], [".c"], ["mcc"])
    assert all("mcc" not in f.name for f in found)


def test_collect_files_warns_missing_root(capsys, tmp_path):
    _collect_files([tmp_path / "nonexistent"], [".c"], [])
    assert "warning" in capsys.readouterr().err


# --- format_files (mocked) ----------------------------------------------------

def test_format_files_uses_bundled_config_by_default(tmp_path):
    (tmp_path / "main.c").write_text("")
    with patch("microchip_devtools.format.uncrustify._run_uncrustify") as mock_run:
        mock_run.return_value = (False, "")
        format_files([tmp_path])
        assert mock_run.call_args[0][1] == str(DEFAULT_CONFIG)


def test_format_files_uses_custom_config_when_provided(tmp_path):
    (tmp_path / "main.c").write_text("")
    with patch("microchip_devtools.format.uncrustify._run_uncrustify") as mock_run:
        mock_run.return_value = (False, "")
        format_files([tmp_path], config="custom.cfg")
        assert mock_run.call_args[0][1] == "custom.cfg"


def test_format_files_returns_0_on_success(tmp_path):
    (tmp_path / "main.c").write_text("")
    with patch("microchip_devtools.format.uncrustify._run_uncrustify", return_value=(False, "")):
        assert format_files([tmp_path]) == 0


def test_format_files_returns_1_on_error(tmp_path):
    (tmp_path / "main.c").write_text("")
    with patch("microchip_devtools.format.uncrustify._run_uncrustify", return_value=(False, "error msg")):
        assert format_files([tmp_path]) == 1
