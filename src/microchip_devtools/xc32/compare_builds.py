"""Compare two PIC32 firmware ELF builds for functional equivalence.

Two builds are considered equal when they have identical:
  - Section sizes  (.text, .data, .bss)
  - Symbol set     (name + type + size for every exported symbol)
  - Config words   (device configuration bits embedded in the hex)

Usage:
    compare-builds <elf_a> <elf_b>
    compare-builds <elf_a> <elf_b> --hex-a <hex_a> --hex-b <hex_b>
    compare-builds                 # resolve all paths from env vars

Environment variables:
    XC32_PATH        XC32 bin dir (default: /opt/microchip/xc32/v4.60/bin/)
    COMPARE_ELF_A    First ELF file
    COMPARE_ELF_B    Second ELF file
    COMPARE_HEX_A    First HEX file  (optional)
    COMPARE_HEX_B    Second HEX file (optional)

Exit codes: 0 = equal, 1 = differ, 2 = argument/tool error
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from rich.console import Console

from microchip_devtools.setup_env.defaults import COMMON_DEFAULTS


def _xc32_tool(name: str) -> str:
    xc32_bin = os.environ.get("XC32_PATH", COMMON_DEFAULTS.get("XC32_PATH", ""))
    return os.path.join(xc32_bin, name) if xc32_bin else name


console = Console(highlight=False)
_err = Console(stderr=True, highlight=False)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_path(cli_val: str | None, env_key: str) -> Path | None:
    v = cli_val or os.environ.get(env_key)
    return Path(v) if v else None


def _run_tool(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return r.stdout
    except FileNotFoundError:
        _err.print(f"[red]ERROR:[/red] tool not found: {cmd[0]}")
        sys.exit(2)
    except subprocess.CalledProcessError as e:
        _err.print(f"[red]ERROR[/red] running {cmd[0]}:\n{e.stderr}")
        sys.exit(2)


def _pass(msg: str) -> None:
    console.print(f"  [green]✔ PASS[/green]  {msg}")


def _fail(msg: str) -> None:
    console.print(f"  [red]✗ FAIL[/red]  {msg}")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def _check_section_sizes(elf_a: Path, elf_b: Path) -> bool:
    console.rule("[bold blue]Section sizes[/bold blue]")

    def parse(elf: Path) -> dict[str, int]:
        out = _run_tool([_xc32_tool("xc32-size"), str(elf)])
        parts = out.strip().splitlines()[1].split()
        return {"text": int(parts[0]), "data": int(parts[1]), "bss": int(parts[2])}

    a, b = parse(elf_a), parse(elf_b)
    passed = True
    for sec in ("text", "data", "bss"):
        if a[sec] == b[sec]:
            _pass(f".{sec:6s}  {a[sec]:>8} bytes")
        else:
            _fail(
                f".{sec:6s}  {a[sec]:>8} bytes  vs  {b[sec]:>8} bytes  (Δ {b[sec]-a[sec]:+d})"
            )
            passed = False
    return passed


def _check_symbols(elf_a: Path, elf_b: Path) -> bool:
    console.rule("[bold blue]Symbols[/bold blue]")

    _SKIP_LOCAL = set("abcdrstvwu")

    def parse(elf: Path) -> set[tuple[str, str, str]]:
        out = _run_tool([_xc32_tool("xc32-nm"), "--print-size", str(elf)])
        symbols: set[tuple[str, str, str]] = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 4:
                continue
            size, sym_type, name = parts[1], parts[2], parts[3]
            if sym_type in _SKIP_LOCAL:
                continue
            symbols.add((sym_type.upper(), size, name))
        return symbols

    a, b = parse(elf_a), parse(elf_b)
    only_a = sorted(a - b)
    only_b = sorted(b - a)

    if not only_a and not only_b:
        _pass(f"All {len(a)} symbols match (name, type, size)")
        return True

    if only_a:
        _fail(f"{len(only_a)} symbol(s) only in {elf_a.name}:")
        for sym in only_a:
            console.print(f"       {sym[0]}  size={sym[1]}  {sym[2]}")

    if only_b:
        _fail(f"{len(only_b)} symbol(s) only in {elf_b.name}:")
        for sym in only_b:
            console.print(f"       {sym[0]}  size={sym[1]}  {sym[2]}")

    return False


def _check_config_words(hex_a: Path, hex_b: Path) -> bool:
    console.rule("[bold blue]Config words[/bold blue]")

    def parse_hex_segments(hex_path: Path) -> dict[int, bytes]:
        segments: dict[int, bytearray] = {}
        base = 0
        with open(hex_path) as f:
            for line in f:
                line = line.strip()
                if not line.startswith(":"):
                    continue
                byte_count = int(line[1:3], 16)
                address = int(line[3:7], 16)
                rec_type = int(line[7:9], 16)
                data = bytes.fromhex(line[9 : 9 + byte_count * 2])
                if rec_type == 0:
                    abs_addr = base + address
                    if abs_addr not in segments:
                        segments[abs_addr] = bytearray()
                    segments[abs_addr] += data
                elif rec_type == 4:
                    base = int(data.hex(), 16) << 16
        return {k: bytes(v) for k, v in segments.items()}

    def config_records(hex_path: Path) -> dict[int, bytes]:
        return {
            addr: data
            for addr, data in parse_hex_segments(hex_path).items()
            if addr >= 0xBFC00000
        }

    cfg_a = config_records(hex_a)
    cfg_b = config_records(hex_b)

    all_addrs = sorted(set(cfg_a) | set(cfg_b))
    passed = True
    for addr in all_addrs:
        da = cfg_a.get(addr, b"")
        db = cfg_b.get(addr, b"")
        if da == db:
            _pass(f"0x{addr:08X}  {da.hex()}")
        else:
            _fail(f"0x{addr:08X}  {da.hex()!r:40s}  vs  {db.hex()!r}")
            passed = False
    return passed


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _run() -> int:
    parser = argparse.ArgumentParser(
        description="Compare two PIC32 firmware builds for functional equivalence.",
        epilog=(
            "Env vars: COMPARE_ELF_A, COMPARE_ELF_B, COMPARE_HEX_A, COMPARE_HEX_B, XC32_PATH"
        ),
    )
    parser.add_argument(
        "elf_a", nargs="?", default=None, help="First ELF (or set COMPARE_ELF_A)"
    )
    parser.add_argument(
        "elf_b", nargs="?", default=None, help="Second ELF (or set COMPARE_ELF_B)"
    )
    parser.add_argument(
        "--hex-a",
        metavar="HEX_A",
        default=None,
        help="First HEX (or set COMPARE_HEX_A)",
    )
    parser.add_argument(
        "--hex-b",
        metavar="HEX_B",
        default=None,
        help="Second HEX (or set COMPARE_HEX_B)",
    )
    args = parser.parse_args()

    elf_a = _resolve_path(args.elf_a, "COMPARE_ELF_A")
    elf_b = _resolve_path(args.elf_b, "COMPARE_ELF_B")
    hex_a = _resolve_path(args.hex_a, "COMPARE_HEX_A")
    hex_b = _resolve_path(args.hex_b, "COMPARE_HEX_B")

    errors: list[str] = []
    if elf_a is None:
        errors.append("ELF A required — pass as positional arg or set COMPARE_ELF_A")
    if elf_b is None:
        errors.append("ELF B required — pass as positional arg or set COMPARE_ELF_B")
    if (hex_a is None) != (hex_b is None):
        errors.append(
            "Must supply both --hex-a/COMPARE_HEX_A and --hex-b/COMPARE_HEX_B or neither"
        )

    if errors:
        for e in errors:
            console.print(f"[red]ERROR:[/red] {e}")
        parser.print_usage(sys.stderr)
        return 2

    for label, p in (("ELF A", elf_a), ("ELF B", elf_b)):
        if not p.exists():
            console.print(f"[red]ERROR:[/red] {label} not found: {p}")
            return 2

    if hex_a is not None:
        for label, p in (("HEX A", hex_a), ("HEX B", hex_b)):
            if not p.exists():
                console.print(f"[red]ERROR:[/red] {label} not found: {p}")
                return 2

    console.print(f"A: {elf_a}")
    console.print(f"B: {elf_b}")

    results = [
        _check_section_sizes(elf_a, elf_b),
        _check_symbols(elf_a, elf_b),
    ]

    if hex_a is not None:
        results.append(_check_config_words(hex_a, hex_b))

    console.print()
    if all(results):
        console.print("[green]✔ Builds are functionally EQUAL[/green]")
        return 0

    console.print("[red]✘ Builds DIFFER[/red]")
    return 1


def main() -> None:
    sys.exit(_run())
