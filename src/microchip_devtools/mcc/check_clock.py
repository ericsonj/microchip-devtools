#!/usr/bin/env python3
"""
microchip_devtools.mcc.check_clock — Validate clock/oscillator configuration.

Checks that clock-related CONFIG keys match expected values in two sources:

  MCC  — core.yml component file (CONFIG_* symbols, authoritative MCC intent)
  CODE — initialization.c pragma directives (#pragma config KEY = VALUE)

Built-in default rules (can be extended or replaced via CLI):
  POSCMOD  = EC        Primary oscillator: External Clock mode
  FPLLICLK = PLL_FRC   PLL input: Internal Fast RC Oscillator
  FPLLMULT = MUL_60    PLL multiplier: 60x
  UPLLEN   = ON        USB PLL enabled

Usage:
    check-clock [--root PATH] [--project-name NAME]
                [--rule KEY=VALUE ...] [--rules-file PATH] [--no-defaults]
                [--verbose]

Exit code:
    0 — all checks passed
    1 — one or more checks failed
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml
from rich.console import Console

from microchip_devtools._project import project_name as _env_project_name
from microchip_devtools._project import project_root as _env_project_root

DEFAULT_RULES: dict[str, str] = {
    "POSCMOD": "EC",
    "FPLLICLK": "PLL_POSC",
    "FPLLMULT": "MUL_40",
    "UPLLEN": "ON",
}

_con = Console(highlight=False)
_err = Console(stderr=True, highlight=False)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _err.print(f"[red][ERROR][/red] File not found: {path}")
        sys.exit(1)


def _parse_mcc_core_yml(text: str) -> dict[str, str]:
    """Extract CONFIG_* symbol values from a MCC core.yml text.

    Navigates the nested structure: symbol → Values child → User child → value.
    """
    doc = yaml.safe_load(text) or {}
    symbols = (doc.get("data") or {}).get("symbols") or {}
    result: dict[str, str] = {}
    for full_key, entry in symbols.items():
        if not full_key.startswith("CONFIG_") or not isinstance(entry, dict):
            continue
        key = full_key.removeprefix("CONFIG_")
        for child in entry.get("children") or []:
            if not isinstance(child, dict) or child.get("type") != "Values":
                continue
            for val_child in child.get("children") or []:
                if isinstance(val_child, dict) and val_child.get("type") == "User":
                    attrs = val_child.get("attributes") or {}
                    val = attrs.get("value")
                    if val is not None:
                        result[key] = str(val)
                    break
            break
    return result


def _parse_pragma_config(text: str) -> dict[str, str]:
    """Extract all #pragma config KEY = VALUE pairs from C source text."""
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r"#pragma\s+config\s+(\w+)\s*=\s*(\S+)", text)
    }


def check_clock_rules(
    mcc: dict[str, str],
    pragma: dict[str, str],
    rules: dict[str, str],
    verbose: bool = False,
) -> int:
    """Check each rule against both MCC and code sources. Returns failure count."""
    failures = 0
    for key, expected in sorted(rules.items()):
        for tag, values in (("MCC ", mcc), ("CODE", pragma)):
            actual = values.get(key)
            if actual is None:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [{tag}] {key:<14} — key not found "
                    f"[dim](expected: {expected})[/dim]"
                )
                failures += 1
            elif actual != expected:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [{tag}] {key:<14} = {actual:<14} "
                    f"[dim](expected: {expected})[/dim]"
                )
                failures += 1
            elif verbose:
                _con.print(f"  [green]✔ PASS[/green]  [{tag}] {key:<14} = {actual}")
    return failures


def _build_rules(
    no_defaults: bool,
    rules_file: Path | None,
    rule_args: list[str] | None,
) -> dict[str, str]:
    rules: dict[str, str] = {} if no_defaults else dict(DEFAULT_RULES)
    if rules_file:
        try:
            loaded = json.loads(rules_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            _err.print(f"[red][ERROR][/red] Cannot load --rules-file: {exc}")
            sys.exit(1)
        rules.update(loaded)
    for pair in rule_args or []:
        key, sep, val = pair.partition("=")
        if not sep or not key.strip() or not val.strip():
            _err.print(f"[red][ERROR][/red] --rule must be KEY=VALUE, got: {pair!r}")
            sys.exit(1)
        rules[key.strip()] = val.strip()
    return rules


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate clock/oscillator configuration (MCC core.yml vs #pragma config)."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Project root (default: $VOLTU_PROJECT_ROOT or cwd)",
    )
    parser.add_argument(
        "--project-name",
        default=None,
        help="Project name (default: $VOLTU_PROJECT_NAME or folder name)",
    )
    parser.add_argument(
        "--rule",
        metavar="KEY=VALUE",
        action="append",
        dest="rules",
        help="Add or override a rule (repeatable). Example: --rule FPLLODIV=DIV_4",
    )
    parser.add_argument(
        "--rules-file",
        type=Path,
        default=None,
        help='JSON file with rules to merge: {"KEY": "VALUE", ...}',
    )
    parser.add_argument(
        "--no-defaults",
        action="store_true",
        help="Skip built-in default rules; use only --rule / --rules-file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show all checks, not just failures",
    )
    args = parser.parse_args()

    root = args.root or _env_project_root()
    name = args.project_name or _env_project_name()

    core_yml_path = root / f"firmware/{name}.X/{name}_default/components/core.yml"
    init_c_path = root / "firmware/src/config/default/initialization.c"

    rules = _build_rules(args.no_defaults, args.rules_file, args.rules)
    if not rules:
        _err.print(
            "[red][ERROR][/red] No rules to check. Use --rule, --rules-file, or remove --no-defaults."
        )
        return 1

    if args.verbose:
        _con.rule("[bold blue]Clock Configuration Check[/bold blue]")
        _con.print()

    core_yml_text = _read(core_yml_path)
    init_c_text = _read(init_c_path)

    mcc = _parse_mcc_core_yml(core_yml_text)
    pragma = _parse_pragma_config(init_c_text)

    if args.verbose:
        _con.print(f"  [dim]core.yml[/dim]          {len(mcc)} CONFIG_* symbol(s)")
        _con.print(
            f"  [dim]initialization.c[/dim]   {len(pragma)} #pragma config directive(s)"
        )
        _con.print(f"  [dim]rules[/dim]              {len(rules)}")
        _con.print()

    failures = check_clock_rules(mcc, pragma, rules, verbose=args.verbose)

    if failures:
        _err.print()
        _err.print(f"  [red bold]FAILED[/red bold] — {failures} check(s) failed.")
        return 1

    if args.verbose:
        _con.print()
        _con.print(
            "  [green bold]PASSED[/green bold] — all clock configuration checks OK."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
