"""Tests for microchip_devtools.format.uncrustify_bin (binary resolver).

No network access: downloads are stubbed, the cache dir is redirected to
tmp_path, and SHA256 pins are patched to match local fixture bytes.
"""

import hashlib

import pytest

from microchip_devtools.format import uncrustify_bin as ub


# --- _platform_key normalization ---------------------------------------------

@pytest.mark.parametrize(
    "system,machine,expected",
    [
        ("Linux", "x86_64", "linux-x86_64"),
        ("Linux", "AMD64", "linux-x86_64"),
        ("Linux", "aarch64", "linux-aarch64"),
        ("Linux", "arm64", "linux-aarch64"),
        ("Windows", "AMD64", "windows-x86_64"),
        ("Windows", "x86_64", "windows-x86_64"),
    ],
)
def test_platform_key_normalizes(monkeypatch, system, machine, expected):
    monkeypatch.setattr(ub.platform, "system", lambda: system)
    monkeypatch.setattr(ub.platform, "machine", lambda: machine)
    assert ub._platform_key() == expected


def test_platform_key_unsupported_os(monkeypatch):
    monkeypatch.setattr(ub.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(ub.platform, "machine", lambda: "arm64")
    with pytest.raises(RuntimeError, match="unsupported OS"):
        ub._platform_key()


def test_platform_key_unsupported_arch(monkeypatch):
    monkeypatch.setattr(ub.platform, "system", lambda: "Linux")
    monkeypatch.setattr(ub.platform, "machine", lambda: "riscv64")
    with pytest.raises(RuntimeError, match="unsupported architecture"):
        ub._platform_key()


# --- env override -------------------------------------------------------------

def test_env_override_returns_existing_file(monkeypatch, tmp_path):
    binary = tmp_path / "my-uncrustify"
    binary.write_text("x")
    monkeypatch.setenv(ub.ENV_OVERRIDE, str(binary))
    assert ub.resolve_uncrustify() == binary


def test_env_override_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setenv(ub.ENV_OVERRIDE, str(tmp_path / "nope"))
    with pytest.raises(RuntimeError, match="does not point to a file"):
        ub.resolve_uncrustify()


# --- cache hit / download path ------------------------------------------------

def _pin_platform(monkeypatch, key="linux-x86_64"):
    monkeypatch.delenv(ub.ENV_OVERRIDE, raising=False)
    monkeypatch.setattr(ub, "_platform_key", lambda: key)


def _redirect_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(ub, "_cache_dir", lambda: tmp_path / "cache")


def test_cache_hit_skips_download(monkeypatch, tmp_path):
    _pin_platform(monkeypatch)
    _redirect_cache(monkeypatch, tmp_path)
    asset_name, _ = ub.BINARIES["linux-x86_64"]

    cached = tmp_path / "cache" / asset_name
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"binary-bytes")
    good_sha = hashlib.sha256(b"binary-bytes").hexdigest()
    monkeypatch.setitem(ub.BINARIES, "linux-x86_64", (asset_name, good_sha))

    def _boom(*a, **k):
        raise AssertionError("download must not be called on cache hit")

    monkeypatch.setattr(ub, "_download", _boom)
    assert ub.resolve_uncrustify() == cached


def test_download_when_cache_missing(monkeypatch, tmp_path):
    _pin_platform(monkeypatch)
    _redirect_cache(monkeypatch, tmp_path)
    asset_name, _ = ub.BINARIES["linux-x86_64"]

    calls = []

    def _fake_download(name, sha, dest):
        calls.append((name, sha, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"downloaded")

    monkeypatch.setattr(ub, "_download", _fake_download)
    result = ub.resolve_uncrustify()
    assert result == tmp_path / "cache" / asset_name
    assert calls and calls[0][0] == asset_name


def test_stale_cache_triggers_redownload(monkeypatch, tmp_path):
    _pin_platform(monkeypatch)
    _redirect_cache(monkeypatch, tmp_path)
    asset_name, sha = ub.BINARIES["linux-x86_64"]

    cached = tmp_path / "cache" / asset_name
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b"WRONG")  # sha won't match the pin

    called = []
    monkeypatch.setattr(ub, "_download", lambda n, s, d: called.append(n))
    ub.resolve_uncrustify()
    assert called == [asset_name]


# --- _download SHA verification ----------------------------------------------

def test_download_rejects_sha_mismatch(monkeypatch, tmp_path):
    dest = tmp_path / "out" / "bin"

    class _Resp:
        def __init__(self):
            self._data = [b"payload", b""]

        def read(self, _n):
            return self._data.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ub.urllib.request, "urlopen", lambda url: _Resp())  # noqa: ARG005
    with pytest.raises(RuntimeError, match="SHA256 mismatch"):
        ub._download("asset", "deadbeef" * 8, dest)
    assert not dest.exists()


def test_download_succeeds_on_sha_match(monkeypatch, tmp_path):
    dest = tmp_path / "out" / "bin"
    payload = b"payload"
    good = hashlib.sha256(payload).hexdigest()

    class _Resp:
        def __init__(self):
            self._data = [payload, b""]

        def read(self, _n):
            return self._data.pop(0)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(ub.urllib.request, "urlopen", lambda url: _Resp())  # noqa: ARG005
    ub._download("asset", good, dest)
    assert dest.read_bytes() == payload
