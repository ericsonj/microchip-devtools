import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from microchip_devtools.xc32.check_clangd import (
    FileResult,
    _parse_errors,
    _should_exclude,
    main,
    run_checks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_compile_commands(tmp_path: Path, files: list[str]) -> Path:
    d = tmp_path / "pymake"
    d.mkdir()
    entries = [{"file": f} for f in files]
    (d / "compile_commands.json").write_text(json.dumps(entries))
    return d


def _mock_run(stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.stderr = stderr
    m.returncode = 0
    return m


# ---------------------------------------------------------------------------
# _parse_errors
# ---------------------------------------------------------------------------

def test_parse_errors_empty():
    assert _parse_errors("") == []


def test_parse_errors_keeps_real_errors():
    text = "E[clangd] foo.c:1:1: error: unknown type name\nE[clangd] foo.c:2:1: error: other"
    result = _parse_errors(text)
    assert len(result) == 2
    assert all(l.startswith("E[") for l in result)


def test_parse_errors_filters_include_cleaner():
    text = "E[clangd] IncludeCleaner: unused include\nE[clangd] foo.c:1:1: real error"
    result = _parse_errors(text)
    assert len(result) == 1
    assert "IncludeCleaner" not in result[0]


def test_parse_errors_excludes_non_E_lines():
    text = "W[clangd] warning line\nI[clangd] info line\nE[clangd] foo.c:1:1: error"
    result = _parse_errors(text)
    assert result == ["E[clangd] foo.c:1:1: error"]


# ---------------------------------------------------------------------------
# _should_exclude
# ---------------------------------------------------------------------------

def test_should_exclude_matches():
    assert _should_exclude("/project/build/foo.c", ["build"]) is True


def test_should_exclude_no_match():
    assert _should_exclude("/project/src/foo.c", ["build"]) is False


def test_should_exclude_empty_patterns():
    assert _should_exclude("/project/src/foo.c", []) is False


def test_should_exclude_multiple_patterns():
    assert _should_exclude("/project/generated/foo.c", ["build", "generated"]) is True


# ---------------------------------------------------------------------------
# run_checks
# ---------------------------------------------------------------------------

FAKE_BIN = Path("/fake/xc32-clangd")


def test_all_pass_returns_0(tmp_path):
    d = _make_compile_commands(tmp_path, ["/src/a.c", "/src/b.c"])
    with patch("microchip_devtools.xc32.check_clangd.subprocess.run", return_value=_mock_run("")):
        assert run_checks(d, [], 2, FAKE_BIN) == 0


def test_error_returns_1(tmp_path):
    d = _make_compile_commands(tmp_path, ["/src/a.c"])
    stderr = "E[clangd] /src/a.c:1:1: error: unknown type name 'uint8_t'"
    with patch("microchip_devtools.xc32.check_clangd.subprocess.run", return_value=_mock_run(stderr)):
        assert run_checks(d, [], 2, FAKE_BIN) == 1


def test_exclude_skips_file(tmp_path):
    d = _make_compile_commands(tmp_path, ["/src/a.c", "/src/generated/b.c"])
    stderr = "E[clangd] /src/generated/b.c:1:1: error: problem"
    mock_run = MagicMock(return_value=_mock_run(""))
    with patch("microchip_devtools.xc32.check_clangd.subprocess.run", mock_run):
        rc = run_checks(d, ["generated"], 2, FAKE_BIN)
    assert rc == 0
    assert mock_run.call_count == 1  # only a.c was checked


def test_missing_compile_commands_returns_1(tmp_path):
    d = tmp_path / "pymake"
    d.mkdir()
    assert run_checks(d, [], 2, FAKE_BIN) == 1


def test_include_cleaner_filtered(tmp_path):
    d = _make_compile_commands(tmp_path, ["/src/a.c"])
    stderr = "E[clangd] IncludeCleaner: /src/a.c unused #include <foo.h>"
    with patch("microchip_devtools.xc32.check_clangd.subprocess.run", return_value=_mock_run(stderr)):
        assert run_checks(d, [], 2, FAKE_BIN) == 0


def test_subprocess_failure_returns_1(tmp_path):
    d = _make_compile_commands(tmp_path, ["/src/a.c"])
    with patch(
        "microchip_devtools.xc32.check_clangd.subprocess.run",
        side_effect=OSError("binary not found"),
    ):
        assert run_checks(d, [], 2, FAKE_BIN) == 1


def test_all_excluded_returns_0(tmp_path):
    d = _make_compile_commands(tmp_path, ["/src/generated/a.c"])
    with patch("microchip_devtools.xc32.check_clangd.subprocess.run") as mock_run:
        rc = run_checks(d, ["generated"], 2, FAKE_BIN)
    assert rc == 0
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_missing_binary_returns_1(tmp_path, monkeypatch):
    monkeypatch.setenv("XC32_PATH", str(tmp_path / "bin"))
    monkeypatch.setattr(sys, "argv", ["check-clangd"])
    assert main() == 1


def test_main_passes_compile_commands_dir(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "xc32-clangd").touch()

    monkeypatch.setenv("XC32_PATH", str(bin_dir))
    monkeypatch.setattr(sys, "argv", [
        "check-clangd",
        "--compile-commands-dir", str(tmp_path / "pymake"),
    ])

    with patch("microchip_devtools.xc32.check_clangd.run_checks", return_value=0) as mock_rc:
        rc = main()

    assert rc == 0
    called_dir = mock_rc.call_args.kwargs["compile_commands_dir"]
    assert called_dir == tmp_path / "pymake"


def test_main_passes_exclude_and_workers(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "xc32-clangd").touch()

    monkeypatch.setenv("XC32_PATH", str(bin_dir))
    monkeypatch.setattr(sys, "argv", [
        "check-clangd",
        "--exclude", "build",
        "--exclude", "generated",
        "--workers", "8",
    ])

    with patch("microchip_devtools.xc32.check_clangd.run_checks", return_value=0) as mock_rc:
        main()

    kwargs = mock_rc.call_args.kwargs
    assert kwargs["exclude"] == ["build", "generated"]
    assert kwargs["workers"] == 8
