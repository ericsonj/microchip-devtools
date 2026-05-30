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

Rule scope:
  --rule       KEY=VALUE   check in BOTH sources (MCC and CODE)
  --rule-code  KEY=VALUE   check in CODE only (#pragma config)
  --rule-mcc   KEY=VALUE   check in MCC only (core.yml CONFIG_*)

Use a scoped flag for keys that live in one source only (e.g. FNOSC, a
#pragma config that may be absent from core.yml when set to its default).

Usage:
    check-clock [--root PATH] [--project-name NAME]
                [--rule KEY=VALUE ...] [--rule-code KEY=VALUE ...]
                [--rule-mcc KEY=VALUE ...] [--rules-file PATH] [--no-defaults]
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
from typing import TypedDict

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


class _RefclkMcc(TypedDict):
    enable: str   # "true" | "false"
    sysclk: int
    rodiv: int
    rotrim: int


class _RefclkCode(TypedDict):
    enabled: bool
    rodiv: int
    rotrim: int


class _PbclkMcc(TypedDict):
    freq: str | None    # "120000000" or None if not declared
    enable: str | None  # "true"/"false" or None if not declared (e.g. PBCLK1)

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


def _parse_pbclk_from_core_yml(text: str, n: int) -> _PbclkMcc:
    """Extract PBCLKn freq and enable from core.yml symbols."""
    doc = yaml.safe_load(text) or {}
    symbols = (doc.get("data") or {}).get("symbols") or {}

    def _user_val(key: str) -> str | None:
        entry = symbols.get(key)
        if not isinstance(entry, dict):
            return None
        for child in entry.get("children") or []:
            if not isinstance(child, dict) or child.get("type") != "Values":
                continue
            for val_child in child.get("children") or []:
                if isinstance(val_child, dict) and val_child.get("type") == "User":
                    attrs = val_child.get("attributes") or {}
                    v = attrs.get("value")
                    return str(v) if v is not None else None
        return None

    return _PbclkMcc(
        freq=_user_val(f"CONFIG_SYS_CLK_PBCLK{n}_FREQ"),
        enable=_user_val(f"CONFIG_SYS_CLK_PBCLK{n}_ENABLE"),
    )


def _parse_pbdiv_from_core_yml(text: str, n: int) -> int | None:
    """Extract CONFIG_SYS_CLK_PBDIV{n} User value (linear divisor) from core.yml."""
    doc = yaml.safe_load(text) or {}
    symbols = (doc.get("data") or {}).get("symbols") or {}
    entry = symbols.get(f"CONFIG_SYS_CLK_PBDIV{n}")
    if not isinstance(entry, dict):
        return None
    for child in entry.get("children") or []:
        if not isinstance(child, dict) or child.get("type") != "Values":
            continue
        for val_child in child.get("children") or []:
            if isinstance(val_child, dict) and val_child.get("type") == "User":
                v = (val_child.get("attributes") or {}).get("value")
                return int(v) if v is not None else None
    return None


def _parse_sysclk_from_core_yml(text: str) -> int:
    """SYS_CLK output freq (Hz): User SYS_CLK_FREQ, else Dynamic CPU_CLOCK_FREQUENCY, else 0."""
    doc = yaml.safe_load(text) or {}
    symbols = (doc.get("data") or {}).get("symbols") or {}

    def _val(key: str, vtype: str) -> str | None:
        entry = symbols.get(key)
        if not isinstance(entry, dict):
            return None
        for child in entry.get("children") or []:
            if not isinstance(child, dict) or child.get("type") != "Values":
                continue
            for vc in child.get("children") or []:
                if isinstance(vc, dict) and vc.get("type") == vtype:
                    v = (vc.get("attributes") or {}).get("value")
                    return str(v) if v is not None else None
        return None

    s = _val("SYS_CLK_FREQ", "User") or _val("CPU_CLOCK_FREQUENCY", "Dynamic") or "0"
    return int(s)


def _parse_refclk_from_core_yml(text: str, n: int) -> _RefclkMcc:
    """Extract REFCLK n parameters from core.yml symbols."""
    doc = yaml.safe_load(text) or {}
    symbols = (doc.get("data") or {}).get("symbols") or {}

    def _user_val(key: str) -> str | None:
        entry = symbols.get(key)
        if not isinstance(entry, dict):
            return None
        for child in entry.get("children") or []:
            if not isinstance(child, dict) or child.get("type") != "Values":
                continue
            for val_child in child.get("children") or []:
                if isinstance(val_child, dict) and val_child.get("type") == "User":
                    attrs = val_child.get("attributes") or {}
                    v = attrs.get("value")
                    return str(v) if v is not None else None
        return None

    def _dynamic_val(key: str) -> str | None:
        entry = symbols.get(key)
        if not isinstance(entry, dict):
            return None
        for child in entry.get("children") or []:
            if not isinstance(child, dict) or child.get("type") != "Values":
                continue
            for val_child in child.get("children") or []:
                if isinstance(val_child, dict) and val_child.get("type") == "Dynamic":
                    attrs = val_child.get("attributes") or {}
                    v = attrs.get("value")
                    return str(v) if v is not None else None
        return None

    enable  = _user_val(f"CONFIG_SYS_CLK_REFCLK{n}_ENABLE") or "false"
    rodiv_s = _user_val(f"CONFIG_SYS_CLK_RODIV{n}") or "0"
    rotrim_s = _user_val(f"CONFIG_SYS_CLK_ROTRIM{n}") or "0"
    sysclk_s = (_user_val("SYS_CLK_FREQ") or _dynamic_val("CPU_CLOCK_FREQUENCY") or "0")

    return _RefclkMcc(
        enable=enable.lower(),
        sysclk=int(sysclk_s),
        rodiv=int(rodiv_s),
        rotrim=int(rotrim_s),
    )


def _parse_refclk_from_plib_clk(text: str, n: int) -> _RefclkCode:
    """Decode REFCLK n register values from plib_clk.c."""
    con_m = re.search(rf'\bREFO{n}CON\s*=\s*(0x[0-9a-fA-F]+)', text)
    trim_m = re.search(rf'\bREFO{n}TRIM\s*=\s*(0x[0-9a-fA-F]+)', text)
    set_m  = re.search(rf'\bREFO{n}CONSET\s*=\s*(0x[0-9a-fA-F]+)', text)

    rodiv  = ((int(con_m.group(1), 16) >> 16) & 0x0FFF) if con_m else 0
    rotrim = ((int(trim_m.group(1), 16) >> 23) & 0x1FF) if trim_m else 0
    enabled = bool(set_m and (int(set_m.group(1), 16) & 0x8000))

    return _RefclkCode(enabled=enabled, rodiv=rodiv, rotrim=rotrim)


def _parse_pbdiv_from_plib_clk(text: str, n: int) -> int | None:
    """Decode PB{n}DIVbits.PBDIV from plib_clk.c → linear divisor (2 ** field)."""
    m = re.search(rf'\bPB{n}DIVbits\.PBDIV\s*=\s*(\d+)\s*;', text)
    if not m:
        return None
    return 2 ** int(m.group(1))


def _compute_refclk_freq(sysclk: int, rodiv: int, rotrim: int) -> float:
    """freq = SYSCLK / (2 * RODIV * (1 + ROTRIM / 512))"""
    if rodiv == 0:
        return 0.0
    return sysclk / (2 * rodiv * (1 + rotrim / 512))


def _parse_pragma_config(text: str) -> dict[str, str]:
    """Extract all #pragma config KEY = VALUE pairs from C source text."""
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r"#pragma\s+config\s+(\w+)\s*=\s*(\S+)", text)
    }


def check_pbclk_rules(
    core_yml_text: str,
    pbclk_rules: dict[str, str],
    verbose: bool = False,
    plib_clk_text: str = "",
    init_c_text: str = "",
) -> int:
    """Check PBCLKn FREQ, ENABLE and DIV rules against core.yml and plib_clk.c."""
    failures = 0

    for key, expected in sorted(pbclk_rules.items()):
        m = re.match(r'^PBCLK(\d+)_(FREQ|ENABLE|DIV)$', key)
        if not m:
            _err.print(f"[red][ERROR][/red] --pbclk-rule key must be PBCLKn_FREQ, PBCLKn_ENABLE, or PBCLKn_DIV, got: {key!r}")
            failures += 1
            continue

        n, kind = int(m.group(1)), m.group(2)
        mcc = _parse_pbclk_from_core_yml(core_yml_text, n)

        if kind == "FREQ":
            mcc_freq = mcc["freq"]
            if mcc_freq is None:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [MCC ] PBCLK{n}_FREQ   — key not found "
                    f"[dim](expected: {expected})[/dim]"
                )
                failures += 1
            elif mcc_freq != expected:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [MCC ] PBCLK{n}_FREQ   = {mcc_freq:<14} "
                    f"[dim](expected: {expected})[/dim]"
                )
                failures += 1
            elif verbose:
                _con.print(f"  [green]✔ PASS[/green]  [MCC ] PBCLK{n}_FREQ   = {mcc_freq}")

        elif kind == "ENABLE":
            mcc_enable = mcc["enable"]
            if mcc_enable is None and n == 1:
                mcc_enable = "true"  # PBCLK1 has no enable symbol — always on
            if mcc_enable is None:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [MCC ] PBCLK{n}_ENABLE — key not found "
                    f"[dim](expected: {expected})[/dim]"
                )
                failures += 1
            elif mcc_enable != expected.lower():
                _err.print(
                    f"  [red]✗ FAIL[/red]  [MCC ] PBCLK{n}_ENABLE = {mcc_enable:<10} "
                    f"[dim](expected: {expected})[/dim]"
                )
                failures += 1
            elif verbose:
                _con.print(f"  [green]✔ PASS[/green]  [MCC ] PBCLK{n}_ENABLE = {mcc_enable}")

        else:  # DIV
            expected_div = int(expected)
            mcc_div  = _parse_pbdiv_from_core_yml(core_yml_text, n)
            code_div = _parse_pbdiv_from_plib_clk(plib_clk_text, n)

            if mcc_div is None:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [MCC ] PBCLK{n}_DIV    — key not found "
                    f"[dim](expected: {expected_div})[/dim]"
                )
                failures += 1
            elif mcc_div != expected_div:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [MCC ] PBCLK{n}_DIV    = {mcc_div:<14} "
                    f"[dim](expected: {expected_div})[/dim]"
                )
                failures += 1
            elif verbose:
                _con.print(f"  [green]✔ PASS[/green]  [MCC ] PBCLK{n}_DIV    = {mcc_div}")

            if code_div is None:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [CODE] PBCLK{n}_DIV    — register not found "
                    f"[dim](expected: {expected_div}, PB{n}DIVbits.PBDIV)[/dim]"
                )
                failures += 1
            elif code_div != expected_div:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [CODE] PBCLK{n}_DIV    = {code_div:<14} "
                    f"[dim](expected: {expected_div}, PB{n}DIVbits.PBDIV)[/dim]"
                )
                failures += 1
            elif verbose:
                annot = f"PB{n}DIVbits.PBDIV"
                fnosc = _parse_pragma_config(init_c_text).get("FNOSC")
                if fnosc == "SPLL":
                    sysclk = _parse_sysclk_from_core_yml(core_yml_text)
                    pbfreq = sysclk // code_div if code_div else 0
                    annot += f"   SPLL {pbfreq}Hz"
                elif fnosc:
                    annot += f"   {fnosc}"
                _con.print(f"  [green]✔ PASS[/green]  [CODE] PBCLK{n}_DIV    = {code_div} [dim]({annot})[/dim]")

    return failures


def check_refclk_rules(
    core_yml_text: str,
    plib_clk_text: str,
    refclk_rules: dict[str, str],
    verbose: bool = False,
) -> int:
    """Check REFCLK enable and frequency rules against core.yml and plib_clk.c."""
    failures = 0
    seen_n: set[int] = set()

    for key, expected in sorted(refclk_rules.items()):
        m = re.match(r'^REFCLK(\d+)_(ENABLE|FREQ)$', key)
        if not m:
            _err.print(f"[red][ERROR][/red] --refclk-rule key must be REFCLKn_ENABLE or REFCLKn_FREQ, got: {key!r}")
            failures += 1
            continue

        n, kind = int(m.group(1)), m.group(2)
        if n not in seen_n:
            seen_n.add(n)

        mcc  = _parse_refclk_from_core_yml(core_yml_text, n)
        code = _parse_refclk_from_plib_clk(plib_clk_text, n)

        if kind == "ENABLE":
            expected_bool = expected.lower() == "true"
            mcc_ok  = mcc["enable"] == expected.lower()
            code_ok = code["enabled"] == expected_bool

            if not mcc_ok:
                _err.print(
                    f"  [red]✗ FAIL[/red]  [MCC ] REFCLK{n}_ENABLE = {mcc['enable']:<10} "
                    f"[dim](expected: {expected})[/dim]"
                )
                failures += 1
            elif verbose:
                _con.print(f"  [green]✔ PASS[/green]  [MCC ] REFCLK{n}_ENABLE = {mcc['enable']}")

            if not code_ok:
                actual_s = "true" if code["enabled"] else "false"
                _err.print(
                    f"  [red]✗ FAIL[/red]  [CODE] REFCLK{n}_ENABLE = {actual_s:<10} "
                    f"[dim](expected: {expected}, ON bit in REFO{n}CONSET)[/dim]"
                )
                failures += 1
            elif verbose:
                _con.print(f"  [green]✔ PASS[/green]  [CODE] REFCLK{n}_ENABLE = {'true' if code['enabled'] else 'false'}")

        else:  # FREQ
            expected_hz = float(expected)

            mcc_freq  = _compute_refclk_freq(mcc["sysclk"], mcc["rodiv"], mcc["rotrim"])
            code_freq = _compute_refclk_freq(mcc["sysclk"], code["rodiv"], code["rotrim"])

            for tag, freq in (("MCC ", mcc_freq), ("CODE", code_freq)):
                if abs(freq - expected_hz) > 1.0:
                    _err.print(
                        f"  [red]✗ FAIL[/red]  [{tag}] REFCLK{n}_FREQ   = {freq:<14.0f} "
                        f"[dim](expected: {expected_hz:.0f} Hz)[/dim]"
                    )
                    failures += 1
                elif verbose:
                    _con.print(
                        f"  [green]✔ PASS[/green]  [{tag}] REFCLK{n}_FREQ   = {freq:.0f} Hz"
                    )

    return failures


def check_scoped_rules(
    values: dict[str, str],
    rules: dict[str, str],
    tag: str,
    verbose: bool = False,
) -> int:
    """Check rules against a SINGLE source (MCC or CODE). tag is the display label."""
    failures = 0
    for key, expected in sorted(rules.items()):
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


def check_clock_rules(
    mcc: dict[str, str],
    pragma: dict[str, str],
    rules: dict[str, str],
    verbose: bool = False,
) -> int:
    """Check each rule against both MCC and code sources. Returns failure count."""
    failures = 0
    for key, expected in sorted(rules.items()):
        single = {key: expected}
        failures += check_scoped_rules(mcc, single, "MCC ", verbose=verbose)
        failures += check_scoped_rules(pragma, single, "CODE", verbose=verbose)
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


def _parse_kv_pairs(pairs: list[str] | None, flag: str) -> dict[str, str]:
    """Parse repeatable KEY=VALUE CLI args into a dict. Aborts on malformed input."""
    out: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, val = pair.partition("=")
        if not sep or not key.strip() or not val.strip():
            _err.print(f"[red][ERROR][/red] {flag} must be KEY=VALUE, got: {pair!r}")
            sys.exit(1)
        out[key.strip()] = val.strip()
    return out


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
        "--rule-code",
        metavar="KEY=VALUE",
        action="append",
        dest="rules_code",
        help="Rule checked in CODE only (#pragma config), repeatable. Example: --rule-code FNOSC=SPLL",
    )
    parser.add_argument(
        "--rule-mcc",
        metavar="KEY=VALUE",
        action="append",
        dest="rules_mcc",
        help="Rule checked in MCC only (core.yml CONFIG_*), repeatable. Example: --rule-mcc FNOSC=SPLL",
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
        "--refclk-rule",
        metavar="KEY=VALUE",
        action="append",
        dest="refclk_rules",
        help=(
            "REFCLK rule (repeatable). "
            "Examples: --refclk-rule REFCLK4_ENABLE=true --refclk-rule REFCLK4_FREQ=40000000"
        ),
    )
    parser.add_argument(
        "--pbclk-rule",
        metavar="KEY=VALUE",
        action="append",
        dest="pbclk_rules",
        help=(
            "PBCLK rule (repeatable). "
            "Examples: --pbclk-rule PBCLK1_FREQ=120000000 --pbclk-rule PBCLK1_DIV=1 --pbclk-rule PBCLK2_ENABLE=true"
        ),
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
    init_c_path   = root / "firmware/src/config/default/initialization.c"
    plib_clk_path = root / "firmware/src/config/default/peripheral/clk/plib_clk.c"

    rules = _build_rules(args.no_defaults, args.rules_file, args.rules)
    rules_code = _parse_kv_pairs(args.rules_code, "--rule-code")
    rules_mcc  = _parse_kv_pairs(args.rules_mcc,  "--rule-mcc")
    refclk_rules = _parse_kv_pairs(args.refclk_rules, "--refclk-rule")
    pbclk_rules  = _parse_kv_pairs(args.pbclk_rules,  "--pbclk-rule")

    if not rules and not rules_code and not rules_mcc and not refclk_rules and not pbclk_rules:
        _err.print(
            "[red][ERROR][/red] No rules to check. Use --rule, --rule-code, --rule-mcc, --rules-file, --refclk-rule, --pbclk-rule, or remove --no-defaults."
        )
        return 1

    if args.verbose:
        _con.rule("[bold blue]Clock Configuration Check[/bold blue]")
        _con.print()

    core_yml_text = _read(core_yml_path)
    failures = 0

    init_c_text: str | None = None
    plib_clk_text: str | None = None
    mcc: dict[str, str] | None = None
    pragma: dict[str, str] | None = None

    # Parse each source once, only when a rule that needs it is present.
    if rules or rules_mcc:
        mcc = _parse_mcc_core_yml(core_yml_text)
    if rules or rules_code:
        init_c_text = _read(init_c_path)
        pragma = _parse_pragma_config(init_c_text)

    if rules:
        if args.verbose:
            _con.print(f"  [dim]core.yml[/dim]          {len(mcc or {})} CONFIG_* symbol(s)")
            _con.print(
                f"  [dim]initialization.c[/dim]   {len(pragma or {})} #pragma config directive(s)"
            )
            _con.print(f"  [dim]rules[/dim]              {len(rules)}")
            _con.print()

        failures += check_clock_rules(mcc or {}, pragma or {}, rules, verbose=args.verbose)

    if rules_code:
        failures += check_scoped_rules(pragma or {}, rules_code, "CODE", verbose=args.verbose)

    if rules_mcc:
        failures += check_scoped_rules(mcc or {}, rules_mcc, "MCC ", verbose=args.verbose)

    if refclk_rules:
        if plib_clk_text is None:
            plib_clk_text = _read(plib_clk_path)

        if args.verbose:
            _con.print(f"  [dim]plib_clk.c[/dim]        {len(refclk_rules)} REFCLK rule(s)")
            _con.print()

        failures += check_refclk_rules(core_yml_text, plib_clk_text, refclk_rules, verbose=args.verbose)

    if pbclk_rules:
        needs_div = any(re.match(r'^PBCLK\d+_DIV$', k) for k in pbclk_rules)
        if needs_div and plib_clk_text is None:
            plib_clk_text = _read(plib_clk_path)
        if needs_div and init_c_text is None:
            init_c_text = _read(init_c_path)

        if args.verbose:
            _con.print(f"  [dim]core.yml[/dim]          {len(pbclk_rules)} PBCLK rule(s)")
            _con.print()

        failures += check_pbclk_rules(
            core_yml_text,
            pbclk_rules,
            verbose=args.verbose,
            plib_clk_text=plib_clk_text or "",
            init_c_text=init_c_text or "",
        )

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
