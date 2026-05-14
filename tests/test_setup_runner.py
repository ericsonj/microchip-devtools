"""Tests for microchip_devtools.setup_env.runner (check orchestration and _resolve)."""

import os
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from microchip_devtools.setup_env.defaults import COMMON_DEFAULTS
from microchip_devtools.setup_env.runner import _resolve, check

# ---------------------------------------------------------------------------
# _resolve
# ---------------------------------------------------------------------------


def test_resolve_shell_env_overrides_default(monkeypatch):
    monkeypatch.setenv("XC32_PATH", "/custom/bin")
    assert _resolve("XC32_PATH", {"XC32_PATH": "/default/bin"}) == "/custom/bin"


def test_resolve_uses_default_when_env_not_set(monkeypatch):
    monkeypatch.delenv("XC32_PATH", raising=False)
    assert _resolve("XC32_PATH", {"XC32_PATH": "/default/bin"}) == "/default/bin"


def test_resolve_expands_tilde(monkeypatch):
    monkeypatch.delenv("DFP_PATH", raising=False)
    result = _resolve("DFP_PATH", {"DFP_PATH": "~/.mchp_packs/dfp"})
    assert result.startswith("/")
    assert "~" not in result


def test_resolve_missing_key_returns_empty(monkeypatch):
    monkeypatch.delenv("UNKNOWN_KEY", raising=False)
    assert _resolve("UNKNOWN_KEY", {}) == ""


def test_resolve_env_takes_precedence_over_empty_default(monkeypatch):
    monkeypatch.setenv("MPLAB_IDE", "/opt/mplab/mplab_ide")
    assert _resolve("MPLAB_IDE", {"MPLAB_IDE": ""}) == "/opt/mplab/mplab_ide"


# ---------------------------------------------------------------------------
# check() orchestration helpers
# ---------------------------------------------------------------------------

_CHECK_TARGETS = [
    "microchip_devtools.setup_env.runner.check_python",
    "microchip_devtools.setup_env.runner.check_poetry",
    "microchip_devtools.setup_env.runner.check_make",
    "microchip_devtools.setup_env.runner.check_cppcheck",
    "microchip_devtools.setup_env.runner.check_uncrustify",
    "microchip_devtools.setup_env.runner.check_xc32",
    "microchip_devtools.setup_env.runner.check_dfp",
    "microchip_devtools.setup_env.runner.check_mplab_ide",
    "microchip_devtools.setup_env.runner.check_file_exists",
    "microchip_devtools.setup_env.runner.check_programmer",
]


def _patch_checks(overrides: dict | None = None):
    """Return (ExitStack, mocks_dict) with all check_* functions patched to True."""
    retvals = {t: True for t in _CHECK_TARGETS}
    if overrides:
        retvals.update(overrides)
    stack = ExitStack()
    mocks = {
        t: stack.enter_context(patch(t, return_value=v)) for t, v in retvals.items()
    }
    return stack, mocks


def _full_defaults(tmp_path):
    return COMMON_DEFAULTS | {"BOOT_ELF": str(tmp_path / "boot.elf")}


# ---------------------------------------------------------------------------
# check() orchestration
# ---------------------------------------------------------------------------


def test_check_all_pass_returns_true(tmp_path, monkeypatch):
    for key in COMMON_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("BOOT_ELF", raising=False)
    stack, _ = _patch_checks()
    with stack:
        assert check(_full_defaults(tmp_path), tmp_path / ".env") is True


def test_check_one_fail_returns_false(tmp_path, monkeypatch):
    for key in COMMON_DEFAULTS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("BOOT_ELF", raising=False)
    stack, _ = _patch_checks({"microchip_devtools.setup_env.runner.check_xc32": False})
    with stack:
        assert check(_full_defaults(tmp_path), tmp_path / ".env") is False


def test_check_mplab_ide_fail_returns_false(tmp_path, monkeypatch):
    monkeypatch.delenv("MPLAB_IDE", raising=False)
    stack, _ = _patch_checks(
        {"microchip_devtools.setup_env.runner.check_mplab_ide": False}
    )
    with stack:
        assert check({"MPLAB_IDE": ""}, tmp_path / ".env") is False


def test_check_skips_xc32_when_not_in_defaults(tmp_path):
    stack, mocks = _patch_checks()
    with stack:
        check({}, tmp_path / ".env")
    mocks["microchip_devtools.setup_env.runner.check_xc32"].assert_not_called()


def test_check_skips_dfp_when_not_in_defaults(tmp_path):
    stack, mocks = _patch_checks()
    with stack:
        check({}, tmp_path / ".env")
    mocks["microchip_devtools.setup_env.runner.check_dfp"].assert_not_called()


def test_check_skips_boot_elf_when_not_in_defaults(tmp_path):
    stack, mocks = _patch_checks()
    with stack:
        check({}, tmp_path / ".env")
    mocks["microchip_devtools.setup_env.runner.check_file_exists"].assert_not_called()


def test_check_skips_programmer_when_not_in_defaults(tmp_path):
    stack, mocks = _patch_checks()
    with stack:
        check({}, tmp_path / ".env")
    mocks["microchip_devtools.setup_env.runner.check_programmer"].assert_not_called()


def test_check_calls_xc32_when_in_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("XC32_PATH", raising=False)
    stack, mocks = _patch_checks()
    with stack:
        check({"XC32_PATH": "/opt/xc32/bin"}, tmp_path / ".env")
    mocks["microchip_devtools.setup_env.runner.check_xc32"].assert_called_once_with(
        "/opt/xc32/bin", tmp_path / ".env"
    )


def test_check_calls_programmer_with_resolved_value(tmp_path, monkeypatch):
    monkeypatch.delenv("PROGRAMMER", raising=False)
    stack, mocks = _patch_checks()
    with stack:
        check({"PROGRAMMER": "PK5"}, tmp_path / ".env")
    mocks[
        "microchip_devtools.setup_env.runner.check_programmer"
    ].assert_called_once_with("PK5")


def test_check_calls_boot_elf_when_in_defaults(tmp_path, monkeypatch):
    monkeypatch.delenv("BOOT_ELF", raising=False)
    elf_path = str(tmp_path / "boot.elf")
    stack, mocks = _patch_checks()
    with stack:
        check({"BOOT_ELF": elf_path}, tmp_path / ".env")
    mocks[
        "microchip_devtools.setup_env.runner.check_file_exists"
    ].assert_called_once_with("BOOT_ELF", elf_path, tmp_path / ".env", False)


def test_check_mplab_ide_always_called(tmp_path, monkeypatch):
    monkeypatch.delenv("MPLAB_IDE", raising=False)
    stack, mocks = _patch_checks()
    with stack:
        check({}, tmp_path / ".env")
    mocks["microchip_devtools.setup_env.runner.check_mplab_ide"].assert_called_once()
