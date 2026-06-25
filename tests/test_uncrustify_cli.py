"""Tests for the transparent ``uncrustify`` passthrough command.

No network / no real binary: the resolver and subprocess.run are stubbed so we
assert only the passthrough contract -- argv forwarded verbatim, exit code
mirrored, resolution failure -> exit 1.
"""

from pathlib import Path

import pytest

from microchip_devtools.format import uncrustify_cli as cli


class _Completed:
    def __init__(self, returncode):
        self.returncode = returncode


def test_forwards_argv_verbatim_and_mirrors_exit(monkeypatch):
    binary = Path("/fake/uncrustify")
    monkeypatch.setattr(cli, "resolve_uncrustify", lambda: binary)
    monkeypatch.setattr(cli.sys, "argv", ["uncrustify", "-c", "x.cfg", "a.c"])

    seen = {}

    def _fake_run(argv):
        seen["argv"] = argv
        return _Completed(7)

    monkeypatch.setattr(cli.subprocess, "run", _fake_run)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert seen["argv"] == [str(binary), "-c", "x.cfg", "a.c"]
    assert exc.value.code == 7


def test_resolution_failure_exits_1(monkeypatch, capsys):
    def _boom():
        raise RuntimeError("SHA256 mismatch")

    monkeypatch.setattr(cli, "resolve_uncrustify", _boom)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 1
    assert "SHA256 mismatch" in capsys.readouterr().err
