#!/usr/bin/env python3
"""
microchip_devtools.xc32.check_clangd — Run xc32-clangd --check on all files.

Reads compile_commands.json, runs xc32-clangd --check on each file in
parallel, and reports any errors. Silent on success.

Usage:
    check-clangd [--compile-commands-dir DIR] [--exclude PATH ...] [--workers N]

Exit code:
    0 — all files passed
    1 — one or more files have errors, or binary/JSON not found
"""

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

_con = Console(highlight=False)
_err = Console(stderr=True, highlight=False)


@dataclass
class FileResult:
    file: str
    errors: list[str] = field(default_factory=list)


def _parse_errors(stderr_text: str) -> list[str]:
    return [
        line for line in stderr_text.splitlines()
        if line.startswith("E[") and "IncludeCleaner" not in line
    ]


def _should_exclude(file_path: str, exclude_patterns: list[str]) -> bool:
    return any(pat in file_path for pat in exclude_patterns)


def _check_file(file: str, clangd_bin: Path, compile_commands_dir: Path) -> FileResult:
    try:
        result = subprocess.run(
            [
                str(clangd_bin),
                f"--compile-commands-dir={compile_commands_dir}",
                f"--check={file}",
            ],
            capture_output=True,
            text=True,
        )
        return FileResult(file=file, errors=_parse_errors(result.stderr))
    except OSError as exc:
        return FileResult(file=file, errors=[f"E[check-clangd] subprocess failed: {exc}"])


def run_checks(
    compile_commands_dir: Path,
    exclude: list[str],
    workers: int,
    clangd_bin: Path,
) -> int:
    compile_commands_path = compile_commands_dir / "compile_commands.json"
    if not compile_commands_path.exists():
        _err.print(f"[red]✗ FAIL[/red]  compile_commands.json not found: {compile_commands_path}")
        return 1

    entries = json.loads(compile_commands_path.read_text(encoding="utf-8"))
    files = [e["file"] for e in entries]
    files = [f for f in files if not _should_exclude(f, exclude)]

    if not files:
        return 0

    results: list[FileResult] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(_check_file, f, clangd_bin, compile_commands_dir): f
            for f in files
        }
        for future in as_completed(futures):
            results.append(future.result())

    failed = [r for r in results if r.errors]
    if not failed:
        return 0

    # Sort for deterministic output order
    failed.sort(key=lambda r: r.file)
    for r in failed:
        _con.rule(f"[bold blue]{r.file}[/bold blue]")
        for line in r.errors:
            _con.print(f"  [red]{line}[/red]")

    _err.print(
        f"\n  [red bold]FAILED[/red bold] — {len(failed)} file(s) with errors."
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run xc32-clangd --check on all files in compile_commands.json."
    )
    parser.add_argument(
        "--compile-commands-dir",
        type=Path,
        default=Path("pymake"),
        metavar="DIR",
        help="Directory containing compile_commands.json (default: pymake)",
    )
    parser.add_argument(
        "--exclude",
        metavar="PATH",
        action="append",
        dest="exclude",
        default=[],
        help="Skip files whose path contains PATH (repeatable)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        metavar="N",
        help="Number of parallel clangd workers (default: 4)",
    )
    args = parser.parse_args()

    xc32_path = os.environ.get("XC32_PATH", "/opt/microchip/xc32/v4.60/bin/")
    clangd_bin = Path(xc32_path) / "xc32-clangd"

    if not clangd_bin.exists():
        _err.print(f"[red]✗ FAIL[/red]  xc32-clangd not found: {clangd_bin}")
        _err.print("  Set [bold]XC32_PATH[/bold] env var to the XC32 bin/ directory.")
        return 1

    return run_checks(
        compile_commands_dir=args.compile_commands_dir,
        exclude=args.exclude,
        workers=args.workers,
        clangd_bin=clangd_bin,
    )


if __name__ == "__main__":
    sys.exit(main())
