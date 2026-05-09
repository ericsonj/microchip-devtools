#!/usr/bin/env python3
"""
voltu_devtools.mcc.check_peripheral — Validate MCC-generated peripheral config files.

Prevents two silent hardware bugs:

  Bug 1 — MIPS interrupt vector stub missing in interrupts_a.S for a handler
           declared in interrupts.c. Without a stub, the ISR never fires.

  Bug 3 — Peripheral clock gated in PMD (plib_clk.c) while enabled in MCC
           (core.yml). PMD registers are write-once per reset.

Usage:
    voltu-check-peripheral [--root PATH] [--project-name NAME] [--stubs-file PATH]

Exit code:
    0 — all checks passed
    1 — one or more checks failed
"""

import argparse
import json
import re
import sys
from pathlib import Path

from voltu_devtools._project import project_name as _env_project_name
from voltu_devtools._project import project_root as _env_project_root


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"[ERROR] File not found: {path}", file=sys.stderr)
        sys.exit(1)


def _fail(msg: str) -> None:
    print(f"[FAIL]  {msg}", file=sys.stderr)


def _ok(msg: str) -> None:
    print(f"[OK]    {msg}")


def _parse_handler_declarations(text: str) -> list[str]:
    return re.findall(r'^void\s+(\w+_Handler)\s*\(void\)\s*;', text, re.MULTILINE)


def _parse_extern_handlers(text: str) -> set[str]:
    return set(re.findall(r'^\s+\.extern\s+(\w+_Handler)', text, re.MULTILINE))


def check_vector_stubs(
    interrupts_c_text: str,
    interrupts_as_text: str,
    known_missing: dict[str, str] | None = None,
) -> int:
    """Bug 1 check: every handler in interrupts.c must have a stub in interrupts_a.S."""
    if known_missing is None:
        known_missing = {}

    declared  = _parse_handler_declarations(interrupts_c_text)
    externed  = _parse_extern_handlers(interrupts_as_text)

    print(f"[INFO] interrupts.c: {len(declared)} handler declaration(s)")
    print(f"[INFO] interrupts_a.S: {len(externed)} .extern handler reference(s)\n")

    failures = 0
    for handler in sorted(declared):
        if handler in known_missing:
            print(f"[SKIP]  {handler}: no stub (accepted — {known_missing[handler]})")
            continue
        if handler not in externed:
            _fail(
                f"{handler} is declared in interrupts.c "
                f"but has NO dispatch stub in interrupts_a.S — "
                f"this interrupt will NEVER fire."
            )
            failures += 1
        else:
            _ok(f"{handler}: stub present in interrupts_a.S")
    return failures


def _parse_pmd_from_core_yml(text: str) -> dict[int, int]:
    pmd_expected: dict[int, int] = {}
    current_reg: int | None = None
    for line in text.splitlines():
        m = re.match(r'\s+PMD(\d+)_REG_VALUE:', line)
        if m:
            current_reg = int(m.group(1))
            continue
        if current_reg is not None:
            mv = re.search(r"value:\s+'(\d+)'", line)
            if mv:
                pmd_expected[current_reg] = int(mv.group(1))
                current_reg = None
                continue
            if re.match(r'\s{4}\w', line) and not re.match(r'\s{6,}', line):
                current_reg = None
    return pmd_expected


def _parse_pmd_from_plib_clk(text: str) -> dict[int, int]:
    pmd_actual: dict[int, int] = {}
    for m in re.finditer(r'\bPMD(\d+)\s*=\s*(0x[0-9a-fA-F]+)[Uu]?\s*;', text):
        pmd_actual[int(m.group(1))] = int(m.group(2), 16)
    return pmd_actual


def check_pmd_registers(core_yml_text: str, plib_clk_text: str) -> int:
    """Bug 3 check: PMD register values in core.yml must match plib_clk.c."""
    pmd_expected = _parse_pmd_from_core_yml(core_yml_text)
    pmd_actual   = _parse_pmd_from_plib_clk(plib_clk_text)

    print(f"[INFO] core.yml: {len(pmd_expected)} PMD register(s) declared")
    print(f"[INFO] plib_clk.c: {len(pmd_actual)} PMD register(s) found\n")

    failures = 0
    for reg in sorted(pmd_expected.keys()):
        expected = pmd_expected[reg]
        if reg not in pmd_actual:
            _fail(
                f"PMD{reg} is declared in core.yml "
                f"but not found in plib_clk.c — cannot verify clock gate."
            )
            failures += 1
            continue
        actual = pmd_actual[reg]
        if actual != expected:
            diff = actual ^ expected
            _fail(
                f"PMD{reg} mismatch — "
                f"plib_clk.c=0x{actual:08X}  core.yml=0x{expected:08X}  "
                f"diff_bits=0x{diff:08X}  "
                f"(MCC regeneration likely reverted a manual clock-enable fix)"
            )
            failures += 1
        else:
            _ok(f"PMD{reg}: 0x{actual:08X} matches core.yml")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate MCC-generated peripheral config files (Bug 1 + Bug 3)."
    )
    parser.add_argument(
        "--root", type=Path, default=None,
        help="Project root (default: $VOLTU_PROJECT_ROOT or cwd)",
    )
    parser.add_argument(
        "--project-name", default=None,
        help="Project name (default: $VOLTU_PROJECT_NAME or folder name)",
    )
    parser.add_argument(
        "--stubs-file", type=Path, default=None,
        help="JSON file with known-missing stubs: {HandlerName: reason}",
    )
    args = parser.parse_args()

    root = args.root or _env_project_root()
    name = args.project_name or _env_project_name()

    interrupts_c  = root / "firmware/src/config/default/interrupts.c"
    interrupts_as = root / "firmware/src/config/default/interrupts_a.S"
    core_yml      = root / f"firmware/{name}.X/{name}_default/components/core.yml"
    plib_clk_c    = root / "firmware/src/config/default/peripheral/clk/plib_clk.c"

    known_missing: dict[str, str] = {}
    if args.stubs_file and args.stubs_file.exists():
        known_missing = json.loads(args.stubs_file.read_text(encoding="utf-8"))
    else:
        default_stubs = root / "pymake" / "check_peripheral_stubs.json"
        if default_stubs.exists():
            known_missing = json.loads(default_stubs.read_text(encoding="utf-8"))

    print("--- Peripheral Configuration Check ---\n")

    interrupts_c_text  = _read(interrupts_c)
    interrupts_as_text = _read(interrupts_as)
    core_yml_text      = _read(core_yml)
    plib_clk_text      = _read(plib_clk_c)

    print("== Bug 1: Vector stubs (interrupts.c vs interrupts_a.S) ==")
    failures  = check_vector_stubs(interrupts_c_text, interrupts_as_text, known_missing)

    print("\n== Bug 3: PMD clock gates (core.yml vs plib_clk.c) ==")
    failures += check_pmd_registers(core_yml_text, plib_clk_text)

    print()
    if failures:
        print(
            f"[RESULT] FAILED — {failures} check(s) failed. "
            f"Fix the generated files or re-run MCC.",
            file=sys.stderr,
        )
        return 1

    print("[RESULT] PASSED — all peripheral configuration checks OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
