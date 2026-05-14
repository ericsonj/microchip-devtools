"""Tests for microchip_devtools.setup_env.checks."""

import sys
from subprocess import CompletedProcess
from unittest.mock import MagicMock, patch

import pytest

from microchip_devtools.setup_env.checks import (
    check_cppcheck,
    check_dfp,
    check_file_exists,
    check_make,
    check_mplab_ide,
    check_poetry,
    check_programmer,
    check_python,
    check_uncrustify,
    check_valid_string,
    check_xc32,
)
from microchip_devtools.setup_env.defaults import PROGRAMMER_VALUES

# ---------------------------------------------------------------------------
# check_python
# ---------------------------------------------------------------------------


def test_check_python_pass(monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 11, 0))
    assert check_python() is True


def test_check_python_fail(monkeypatch):
    monkeypatch.setattr(sys, "version_info", (3, 9, 0))
    assert check_python() is False


# ---------------------------------------------------------------------------
# Tool detection checks: poetry, make, cppcheck, uncrustify
# ---------------------------------------------------------------------------

_TOOL_CHECKS = [
    (check_poetry, "poetry"),
    (check_make, "make"),
    (check_cppcheck, "cppcheck"),
    (check_uncrustify, "uncrustify"),
]


@pytest.mark.parametrize("fn,cmd", _TOOL_CHECKS)
def test_tool_check_pass(fn, cmd):
    ok = CompletedProcess(args=[], returncode=0, stdout=f"{cmd} 1.2.3", stderr="")
    with (
        patch("shutil.which", return_value=f"/usr/bin/{cmd}"),
        patch("subprocess.run", return_value=ok),
    ):
        assert fn() is True


@pytest.mark.parametrize("fn,cmd", _TOOL_CHECKS)
def test_tool_check_not_on_path(fn, cmd):
    with patch("shutil.which", return_value=None):
        assert fn() is False


@pytest.mark.parametrize("fn,cmd", _TOOL_CHECKS)
def test_tool_check_subprocess_exception(fn, cmd):
    with (
        patch("shutil.which", return_value=f"/usr/bin/{cmd}"),
        patch("subprocess.run", side_effect=OSError("exec failed")),
    ):
        assert fn() is False


# ---------------------------------------------------------------------------
# check_xc32
# ---------------------------------------------------------------------------


def _xc32_ok():
    return CompletedProcess(
        args=[], returncode=0, stdout="xc32-gcc (XC32) v4.60\n", stderr=""
    )


def test_check_xc32_pass(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "xc32-gcc").touch()
    with patch("subprocess.run", return_value=_xc32_ok()):
        assert check_xc32(str(bin_dir), tmp_path / ".env") is True


def test_check_xc32_fail_non_interactive(tmp_path):
    with patch("microchip_devtools.setup_env.checks.prompt_path", return_value=None):
        assert check_xc32(str(tmp_path / "missing"), tmp_path / ".env") is False


def test_check_xc32_interactive_fallback(tmp_path):
    alt_dir = tmp_path / "alt_bin"
    alt_dir.mkdir()
    (alt_dir / "xc32-gcc").touch()
    mock_save = MagicMock()
    with (
        patch(
            "microchip_devtools.setup_env.checks.prompt_path", return_value=str(alt_dir)
        ),
        patch("subprocess.run", return_value=_xc32_ok()),
        patch("microchip_devtools.setup_env.checks.offer_save_to_env", mock_save),
    ):
        result = check_xc32(str(tmp_path / "missing"), tmp_path / ".env")
    assert result is True
    mock_save.assert_called_once_with("XC32_PATH", str(alt_dir), tmp_path / ".env")


def test_check_xc32_interactive_fallback_bad_path(tmp_path):
    # User provides a path that also doesn't have xc32-gcc — still fails
    bad_dir = tmp_path / "bad_bin"
    bad_dir.mkdir()
    with patch(
        "microchip_devtools.setup_env.checks.prompt_path", return_value=str(bad_dir)
    ):
        result = check_xc32(str(tmp_path / "missing"), tmp_path / ".env")
    assert result is False


# ---------------------------------------------------------------------------
# check_dfp
# ---------------------------------------------------------------------------


def test_check_dfp_pass(tmp_path):
    dfp_dir = tmp_path / "dfp"
    dfp_dir.mkdir()
    assert check_dfp(str(dfp_dir), tmp_path / ".env") is True


def test_check_dfp_fail_non_interactive(tmp_path):
    with patch("microchip_devtools.setup_env.checks.prompt_path", return_value=None):
        assert check_dfp(str(tmp_path / "missing"), tmp_path / ".env") is False


def test_check_dfp_interactive_fallback(tmp_path):
    alt_dir = tmp_path / "alt_dfp"
    alt_dir.mkdir()
    mock_save = MagicMock()
    with (
        patch(
            "microchip_devtools.setup_env.checks.prompt_path", return_value=str(alt_dir)
        ),
        patch("microchip_devtools.setup_env.checks.offer_save_to_env", mock_save),
    ):
        result = check_dfp(str(tmp_path / "missing"), tmp_path / ".env")
    assert result is True
    mock_save.assert_called_once_with("DFP_PATH", str(alt_dir), tmp_path / ".env")


# ---------------------------------------------------------------------------
# check_mplab_ide
# ---------------------------------------------------------------------------


def test_check_mplab_ide_pass(tmp_path):
    ide_bin = tmp_path / "mplab_ide"
    ide_bin.touch()
    assert check_mplab_ide(str(ide_bin), tmp_path / ".env") is True


def test_check_mplab_ide_none_non_interactive(tmp_path):
    with patch("microchip_devtools.setup_env.checks.prompt_path", return_value=None):
        assert check_mplab_ide(None, tmp_path / ".env") is True


def test_check_mplab_ide_empty_string_returns_true(tmp_path):
    with patch("microchip_devtools.setup_env.checks.prompt_path", return_value=None):
        assert check_mplab_ide("", tmp_path / ".env") is True


def test_check_mplab_ide_bad_path_non_interactive(tmp_path):
    with patch("microchip_devtools.setup_env.checks.prompt_path", return_value=None):
        assert (
            check_mplab_ide(str(tmp_path / "missing_ide"), tmp_path / ".env") is False
        )


def test_check_mplab_ide_interactive_fallback(tmp_path):
    ide_bin = tmp_path / "mplab_ide"
    ide_bin.touch()
    mock_save = MagicMock()
    with (
        patch(
            "microchip_devtools.setup_env.checks.prompt_path", return_value=str(ide_bin)
        ),
        patch("microchip_devtools.setup_env.checks.offer_save_to_env", mock_save),
    ):
        result = check_mplab_ide(None, tmp_path / ".env")
    assert result is True
    mock_save.assert_called_once_with("MPLAB_IDE", str(ide_bin), tmp_path / ".env")


# ---------------------------------------------------------------------------
# check_file_exists
# ---------------------------------------------------------------------------


def test_check_file_exists_pass(tmp_path):
    elf_file = tmp_path / "boot.elf"
    elf_file.touch()
    assert check_file_exists("BOOT_ELF", str(elf_file), tmp_path / ".env") is True


def test_check_file_exists_empty_path_optional_pass(tmp_path):
    assert check_file_exists("BOOT_ELF", "", tmp_path / ".env", optional=True) is True


def test_check_file_exists_empty_path_required_fail(tmp_path):
    assert check_file_exists("BOOT_ELF", "", tmp_path / ".env", optional=False) is False


def test_check_file_exists_fail_non_interactive(tmp_path):
    with patch("microchip_devtools.setup_env.checks.prompt_path", return_value=None):
        result = check_file_exists(
            "BOOT_ELF", str(tmp_path / "missing.elf"), tmp_path / ".env"
        )
    assert result is False


def test_check_file_exists_interactive_fallback(tmp_path):
    elf_file = tmp_path / "boot.elf"
    elf_file.touch()
    mock_save = MagicMock()
    with (
        patch(
            "microchip_devtools.setup_env.checks.prompt_path",
            return_value=str(elf_file),
        ),
        patch("microchip_devtools.setup_env.checks.offer_save_to_env", mock_save),
    ):
        result = check_file_exists(
            "BOOT_ELF", str(tmp_path / "missing.elf"), tmp_path / ".env"
        )
    assert result is True
    mock_save.assert_called_once_with("BOOT_ELF", str(elf_file), tmp_path / ".env")


# ---------------------------------------------------------------------------
# check_programmer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", list(PROGRAMMER_VALUES.keys()))
def test_check_programmer_valid(value):
    assert check_programmer(value) is True


def test_check_programmer_invalid():
    assert check_programmer("UNKNOWN") is False


def test_check_programmer_empty():
    assert check_programmer("") is False


# ---------------------------------------------------------------------------
# check_valid_string
# ---------------------------------------------------------------------------


def test_check_valid_string_pass():
    assert check_valid_string("MY_VAR", "opt_a", ["opt_a", "opt_b"]) is True


def test_check_valid_string_fail():
    assert check_valid_string("MY_VAR", "UNKNOWN", ["opt_a", "opt_b"]) is False


def test_check_valid_string_empty():
    assert check_valid_string("MY_VAR", "", ["opt_a", "opt_b"]) is False
