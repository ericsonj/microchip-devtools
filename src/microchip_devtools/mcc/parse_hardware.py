#!/usr/bin/env python3
"""
microchip_devtools.mcc.parse_hardware — Parse Harmony component YML and report hardware config.

Usage:
    mchp-parse-hardware [--root PATH] [--project-name NAME]
    mchp-parse-hardware --components-dir PATH [--format json] [--output FILE]

Exit codes:
    0 — success
    1 — input/configuration error
    2 — parse error in at least one YML file
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from microchip_devtools._project import project_name as _env_project_name
from microchip_devtools._project import project_root as _env_project_root


@dataclass(frozen=True)
class SymbolRecord:
    component: str
    symbol: str
    value_raw: str
    source_kind: str
    symbol_type: str
    file_path: str


def _err(msg: str) -> None:
    print(f"[ERROR] {msg}", file=sys.stderr)


def _info(msg: str) -> None:
    print(f"[INFO]  {msg}")


def _normalize_bool(value: str) -> bool | None:
    lowered = value.strip().lower()
    if lowered in {"true", "1", "yes", "on"}:
        return True
    if lowered in {"false", "0", "no", "off"}:
        return False
    return None


def _extract_value_meta(symbol_node: dict[str, Any]) -> tuple[str, str]:
    children = symbol_node.get("children", [])
    if not isinstance(children, list):
        return "", "Unknown"

    for child in children:
        if not isinstance(child, dict):
            continue
        if child.get("type") != "Values":
            continue
        entries = child.get("children", [])
        if not isinstance(entries, list) or not entries:
            return "", "Unknown"
        first = entries[0]
        if not isinstance(first, dict):
            return "", "Unknown"
        attrs = first.get("attributes", {})
        if not isinstance(attrs, dict):
            return "", "Unknown"
        return str(attrs.get("value", "")), str(first.get("type", "Unknown"))

    return "", "Unknown"


def _load_component_file(path: Path, root: Path) -> tuple[str, list[SymbolRecord]]:
    text = path.read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("Top-level YAML node is not a mapping")

    component = str(payload.get("componentName", path.stem))
    data = payload.get("data", {})
    symbols = data.get("symbols", {}) if isinstance(data, dict) else {}
    if not isinstance(symbols, dict):
        return component, []

    records: list[SymbolRecord] = []
    for symbol_name, symbol_node in symbols.items():
        if not isinstance(symbol_node, dict):
            continue
        value_raw, source_kind = _extract_value_meta(symbol_node)
        symbol_type = str(symbol_node.get("type", "Unknown"))
        try:
            rel_path = str(path.relative_to(root))
        except ValueError:
            rel_path = str(path)
        records.append(
            SymbolRecord(
                component=component,
                symbol=str(symbol_name),
                value_raw=value_raw,
                source_kind=source_kind,
                symbol_type=symbol_type,
                file_path=rel_path,
            )
        )

    return component, records


def _find_all_yml_files(components_dir: Path) -> list[Path]:
    return sorted(p for p in components_dir.rglob("*.yml") if p.is_file())


def _collect_records(
    components_dir: Path, root: Path
) -> tuple[list[Path], dict[str, list[SymbolRecord]], list[str]]:
    files = _find_all_yml_files(components_dir)
    by_component: dict[str, list[SymbolRecord]] = {}
    parse_errors: list[str] = []

    for file_path in files:
        try:
            component, records = _load_component_file(file_path, root)
        except (yaml.YAMLError, OSError, ValueError) as exc:
            try:
                rel = str(file_path.relative_to(root))
            except ValueError:
                rel = str(file_path)
            parse_errors.append(f"{rel}: {exc}")
            continue
        by_component.setdefault(component, []).extend(records)

    return files, by_component, parse_errors


def _all_records(by_component: dict[str, list[SymbolRecord]]) -> list[SymbolRecord]:
    items: list[SymbolRecord] = []
    for records in by_component.values():
        items.extend(records)
    return items


def _is_clock_symbol(symbol: str) -> bool:
    return bool(re.search(r"(CLOCK|FREQ|PLL|OSC|CLKSEL)", symbol, re.IGNORECASE))


def _is_interrupt_symbol(symbol: str) -> bool:
    return bool(re.search(r"(INTERRUPT|IRQ|IEC)", symbol, re.IGNORECASE))


def _is_comm_timing_symbol(symbol: str) -> bool:
    return bool(re.search(r"(BAUD|BRG|BITRATE|TSEG|SJW|TIMER_PERIOD|TIME_PERIOD_MS)", symbol, re.IGNORECASE))


def _is_adc_symbol(component: str, symbol: str) -> bool:
    if component.lower().startswith("adch"):
        return True
    return bool(re.search(r"ADCHS|ADC", symbol, re.IGNORECASE))


def _build_component_enable_state(records: list[SymbolRecord]) -> str:
    enable_values: list[bool] = []
    for rec in records:
        if "ENABLE" not in rec.symbol.upper():
            continue
        normalized = _normalize_bool(rec.value_raw)
        if normalized is None:
            continue
        enable_values.append(normalized)

    if enable_values:
        return "enabled" if any(enable_values) else "disabled"

    clock_like = [
        rec for rec in records if re.search(r"(CLOCK|FREQ|TIMER_PERIOD)", rec.symbol, re.IGNORECASE)
    ]
    if clock_like and all(rec.value_raw in {"", "0", "0.0"} for rec in clock_like):
        return "disabled"
    if clock_like:
        return "enabled"
    return "unknown"


def _extract_pin_map(records: list[SymbolRecord]) -> dict[str, dict[str, str]]:
    pin_data: dict[str, dict[str, str]] = {}
    pattern = re.compile(r"^BSP_PIN_(\d+)_(FUNCTION_NAME|FUNCTION_TYPE|MODE)$")
    for rec in records:
        match = pattern.match(rec.symbol)
        if not match:
            continue
        pin_num = match.group(1)
        field = match.group(2).lower()
        pin_data.setdefault(pin_num, {})[field] = rec.value_raw
    return pin_data


def _build_report_data(files: list[Path], by_component: dict[str, list[SymbolRecord]], root: Path) -> dict[str, Any]:
    all_recs = _all_records(by_component)

    clocks = [
        {"component": rec.component, "symbol": rec.symbol, "value": rec.value_raw, "source": rec.source_kind}
        for rec in all_recs if _is_clock_symbol(rec.symbol)
    ]

    comm_timing = [
        {"component": rec.component, "symbol": rec.symbol, "value": rec.value_raw, "source": rec.source_kind}
        for rec in all_recs if _is_comm_timing_symbol(rec.symbol)
    ]

    component_status = [
        {"component": name, "status": _build_component_enable_state(records), "file_count": len({rec.file_path for rec in records})}
        for name, records in sorted(by_component.items())
    ]

    interrupt_status = []
    for name, records in sorted(by_component.items()):
        values = []
        for rec in records:
            if not _is_interrupt_symbol(rec.symbol):
                continue
            normalized = _normalize_bool(rec.value_raw)
            if normalized is None:
                continue
            values.append(normalized)
        state = "enabled" if values and any(values) else ("disabled" if values else "unknown")
        interrupt_status.append({"component": name, "interrupts": state})

    core_records = by_component.get("core", [])
    pin_map = _extract_pin_map(core_records)

    adc = [
        {"component": rec.component, "symbol": rec.symbol, "value": rec.value_raw, "source": rec.source_kind}
        for rec in all_recs if _is_adc_symbol(rec.component, rec.symbol)
    ]

    try:
        file_paths = [str(p.relative_to(root)) for p in files]
    except ValueError:
        file_paths = [str(p) for p in files]

    return {
        "overview": {
            "files_scanned": len(files),
            "components_found": len(by_component),
            "symbols_scanned": len(all_recs),
            "component_files": file_paths,
        },
        "clocks": clocks,
        "peripherals": component_status,
        "interrupts": interrupt_status,
        "pin_map": pin_map,
        "communication_timings": comm_timing,
        "adc": adc,
    }


def _format_text(report: dict[str, Any], max_items: int) -> str:
    out: list[str] = []

    overview = report["overview"]
    out.append("== Hardware Configuration Report ==")
    out.append(f"Files scanned: {overview['files_scanned']}")
    out.append(f"Components found: {overview['components_found']}")
    out.append(f"Symbols scanned: {overview['symbols_scanned']}")
    out.append("")

    out.append("== Enabled Peripherals ==")
    for item in report["peripherals"]:
        out.append(f"- {item['component']}: {item['status']}")
    out.append("")

    out.append("== Interrupt Status ==")
    for item in report["interrupts"]:
        out.append(f"- {item['component']}: {item['interrupts']}")
    out.append("")

    out.append("== Clock-Related Symbols ==")
    for rec in report["clocks"][:max_items]:
        out.append(f"- {rec['component']}.{rec['symbol']} = {rec['value']} (source={rec['source']})")
    if len(report["clocks"]) > max_items:
        out.append(f"... {len(report['clocks']) - max_items} more clock entries")
    out.append("")

    out.append("== Communication Timing Symbols ==")
    for rec in report["communication_timings"][:max_items]:
        out.append(f"- {rec['component']}.{rec['symbol']} = {rec['value']} (source={rec['source']})")
    if len(report["communication_timings"]) > max_items:
        out.append(f"... {len(report['communication_timings']) - max_items} more timing entries")
    out.append("")

    out.append("== Pin Mapping (core) ==")
    pin_items = sorted(report["pin_map"].items(), key=lambda x: int(x[0]))
    for pin, fields in pin_items[:max_items]:
        name = fields.get("function_name", "")
        ptype = fields.get("function_type", "")
        mode = fields.get("mode", "")
        out.append(f"- PIN {pin}: name={name}, function={ptype}, mode={mode}")
    if len(pin_items) > max_items:
        out.append(f"... {len(pin_items) - max_items} more pin entries")
    out.append("")

    out.append("== ADC Symbols ==")
    for rec in report["adc"][:max_items]:
        out.append(f"- {rec['component']}.{rec['symbol']} = {rec['value']} (source={rec['source']})")
    if len(report["adc"]) > max_items:
        out.append(f"... {len(report['adc']) - max_items} more ADC entries")

    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse Harmony component YML files and report hardware configuration."
    )
    parser.add_argument("--root", type=Path, default=None,
                        help="Project root (default: $VOLTU_PROJECT_ROOT or cwd)")
    parser.add_argument("--project-name", default=None,
                        help="Project name (default: $VOLTU_PROJECT_NAME or folder name)")
    parser.add_argument("--components-dir", type=Path, default=None,
                        help="Override components directory path")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-items", type=int, default=100)

    args = parser.parse_args(argv)

    root = args.root or _env_project_root()
    name = args.project_name or _env_project_name()

    if args.components_dir is not None:
        components_dir = args.components_dir
        if not components_dir.is_absolute():
            components_dir = root / components_dir
    else:
        components_dir = root / f"firmware/{name}.X/{name}_default/components"

    if not components_dir.exists() or not components_dir.is_dir():
        _err(f"Components directory not found: {components_dir}")
        return 1

    _info(f"Scanning YML files in {components_dir}")
    files, by_component, parse_errors = _collect_records(components_dir, root)
    if parse_errors:
        for item in parse_errors:
            _err(f"Parse failed for {item}")
        return 2

    report = _build_report_data(files, by_component, root)
    if args.format == "json":
        output_text = json.dumps(report, indent=2)
    else:
        output_text = _format_text(report, max_items=args.max_items)

    if args.output:
        target = args.output if args.output.is_absolute() else root / args.output
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(output_text + "\n", encoding="utf-8")
        _info(f"Report written to {target}")
    else:
        print(output_text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
