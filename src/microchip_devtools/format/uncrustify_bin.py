#!/usr/bin/env python3
"""
microchip_devtools.format.uncrustify_bin — resolve a pinned uncrustify binary.

The ``format`` command requires a specific uncrustify version so that
formatting is byte-reproducible across machines. System packages no longer
ship a matching version, so instead of relying on ``$PATH`` we download a
prebuilt binary (built in CI, published as a GitHub Release asset), verify its
SHA256 against a pin, and cache it locally.

Resolution order in :func:`resolve_uncrustify`:
    1. ``MICROCHIP_DEVTOOLS_UNCRUSTIFY`` env var (explicit override / air-gapped).
    2. Cached binary whose SHA256 matches the pin.
    3. Download from the GitHub Release, verify, cache.
"""

import hashlib
import os
import platform
import stat
import tempfile
import urllib.request
from pathlib import Path

from rich.console import Console

UNCRUSTIFY_VERSION = "0.72.0"
RELEASE_TAG = "uncrustify-bin-v0.72.0"
GH_RELEASE_BASE = (
    "https://github.com/ericsonj/microchip-devtools/releases/download/" + RELEASE_TAG
)
ENV_OVERRIDE = "MICROCHIP_DEVTOOLS_UNCRUSTIFY"

# platform_key -> (asset_name, sha256). SHA256 values are filled in once the
# build-uncrustify.yml workflow has produced and published the binaries.
BINARIES: dict[str, tuple[str, str]] = {
    "linux-x86_64": (
        f"uncrustify-{UNCRUSTIFY_VERSION}-linux-x86_64",
        "d87ce91ad486acf6cee3f8c85b1bb240ccccfd2081ba4fdb28227effbb7ddf76",
    ),
    "linux-aarch64": (
        f"uncrustify-{UNCRUSTIFY_VERSION}-linux-aarch64",
        "97a57d022f139306e1fa96f484727c9370aae25444030f9f083dd04d7d9aad1b",
    ),
    "windows-x86_64": (
        f"uncrustify-{UNCRUSTIFY_VERSION}-windows-x86_64.exe",
        "272c46424ed00f9580475b59f2e4d6ba820964e7938d52f54bb823aa404f5ea4",
    ),
}

_console = Console()


def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "linux":
        os_part = "linux"
    elif system == "windows":
        os_part = "windows"
    else:
        raise RuntimeError(
            f"uncrustify: unsupported OS {platform.system()!r}. "
            f"Supported: {', '.join(sorted(BINARIES))}."
        )

    if machine in ("x86_64", "amd64"):
        arch_part = "x86_64"
    elif machine in ("aarch64", "arm64"):
        arch_part = "aarch64"
    else:
        raise RuntimeError(
            f"uncrustify: unsupported architecture {platform.machine()!r}. "
            f"Supported: {', '.join(sorted(BINARIES))}."
        )

    key = f"{os_part}-{arch_part}"
    if key not in BINARIES:
        raise RuntimeError(
            f"uncrustify: no prebuilt binary for {key!r}. "
            f"Supported: {', '.join(sorted(BINARIES))}."
        )
    return key


def _cache_dir() -> Path:
    if platform.system().lower() == "windows":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "microchip-devtools" / f"uncrustify-{UNCRUSTIFY_VERSION}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _make_executable(path: Path) -> None:
    if platform.system().lower() != "windows":
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download(asset_name: str, sha256: str, dest: Path) -> None:
    url = f"{GH_RELEASE_BASE}/{asset_name}"
    dest.parent.mkdir(parents=True, exist_ok=True)

    _console.print(f"[cyan]↓ downloading uncrustify {UNCRUSTIFY_VERSION}[/cyan] ({asset_name})")

    fd, tmp_name = tempfile.mkstemp(dir=str(dest.parent), suffix=".part")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(url) as resp:  # noqa: S310
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                out.write(chunk)

        actual = _sha256(tmp)
        if actual != sha256:
            raise RuntimeError(
                f"uncrustify: SHA256 mismatch for {asset_name}\n"
                f"  expected {sha256}\n  actual   {actual}"
            )

        _make_executable(tmp)
        tmp.replace(dest)
    finally:
        if tmp.exists():
            tmp.unlink()


def resolve_uncrustify() -> Path:
    """Return a path to a verified, executable pinned uncrustify binary."""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        path = Path(override)
        if not path.is_file():
            raise RuntimeError(
                f"uncrustify: {ENV_OVERRIDE}={override!r} does not point to a file."
            )
        return path

    key = _platform_key()
    asset_name, sha256 = BINARIES[key]
    dest = _cache_dir() / asset_name

    if dest.is_file() and _sha256(dest) == sha256:
        return dest

    _download(asset_name, sha256, dest)
    return dest
