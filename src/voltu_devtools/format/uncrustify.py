#!/usr/bin/env python3
"""
voltu_devtools.format.uncrustify — Python wrapper for uncrustify.

Walks one or more source roots, collects C/H files, runs uncrustify,
and reports which files were actually reformatted.

CLI usage:
    voltu-format firmware/src -c uncrustifyVoltuC.cfg -x config mcc build

Python usage:
    from voltu_devtools.format.uncrustify import format_files
    rc = format_files(roots=["firmware/src"], config="style.cfg", exclude=["config"])
"""

import argparse
import subprocess
import sys
from pathlib import Path

DEFAULT_EXTENSIONS: list[str] = [".c", ".h"]
DEFAULT_CONFIG: str = "uncrustifyVoltuC.cfg"


def _collect_files(
    roots: list[Path],
    extensions: list[str],
    exclude: list[str],
) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            print(f"uncrustify: warning: root not found: {root}", file=sys.stderr)
            continue
        for ext in extensions:
            for path in sorted(root.rglob(f"*{ext}")):
                rel = path.as_posix()
                if not any(pat in rel for pat in exclude):
                    found.append(path)
    return found


def _run_uncrustify(path: Path, config: str) -> tuple[bool, str]:
    mtime_before = path.stat().st_mtime
    result = subprocess.run(
        [
            "uncrustify",
            "-c", config,
            "--replace",
            "--no-backup",
            "--if-changed",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        msg = (result.stderr or result.stdout).strip()
        return False, msg

    changed = path.stat().st_mtime != mtime_before
    return changed, ""


def format_files(
    roots: list[str | Path],
    config: str = DEFAULT_CONFIG,
    extensions: list[str] | None = None,
    exclude: list[str] | None = None,
) -> int:
    if extensions is None:
        extensions = DEFAULT_EXTENSIONS
    if exclude is None:
        exclude = []

    root_paths = [Path(r) for r in roots]
    files = _collect_files(root_paths, extensions, exclude)

    if not files:
        print("uncrustify: no files matched — check roots and exclude patterns")
        return 0

    formatted: list[Path] = []
    errors: list[tuple[Path, str]] = []

    for path in files:
        changed, err = _run_uncrustify(path, config)
        if err:
            errors.append((path, err))
        elif changed:
            formatted.append(path)

    for f in formatted:
        print(f"    FM  {f}")

    if errors:
        print(f"\n  [{len(errors)} error(s)]", file=sys.stderr)
        for f, msg in errors:
            print(f"  ERROR  {f}\n         {msg}", file=sys.stderr)
        return 1

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run uncrustify on a source tree and report reformatted files.",
    )
    parser.add_argument("roots", nargs="+", metavar="ROOT")
    parser.add_argument("-c", "--config", default=DEFAULT_CONFIG, metavar="FILE")
    parser.add_argument("-e", "--ext", nargs="+", default=DEFAULT_EXTENSIONS, metavar="EXT")
    parser.add_argument("-x", "--exclude", nargs="+", default=[], metavar="PATTERN")

    args = parser.parse_args()
    sys.exit(format_files(args.roots, args.config, args.ext, args.exclude))


if __name__ == "__main__":
    main()
