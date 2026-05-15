#!/usr/bin/env python3
"""
microchip_devtools.xc32.merge_hex — Merge bootloader + app HEX into a single image.

Optionally patches:
  - A signature word at a given physical address (for bootloader app-valid checks)
  - DEVCFG0 config bits to enable EJTAG debugging (PIC32MK-specific)

Usage (boot ELF + prepared app HEX):
    merge-hex --boot-elf boot.elf --app-hex app_prepared.hex -o out.hex

Usage (legacy HEX positional):
    merge-hex boot.hex app.hex out.hex [options]

Options:
    --boot-elf FILE     Bootloader ELF — auto-generates .hex if absent, auto-detects --ejtag-addr
    --app-hex FILE      App HEX already post-processed with srec_cat fill/crop
    -o / --output FILE  Output file (named alternative to positional out)
    --sig-addr ADDR     Physical address to write the signature word (hex, e.g. 0x1D0FFFF8)
    --sig-word VALUE    Signature word value (hex, default: 0x00000000)
    --ejtag-addr ADDR   Physical address of DEVCFG0 config word for EJTAG enable (optional)
If --sig-addr is omitted, no signature patch is applied, except in --app-hex mode
where the bootloader app-valid signature defaults to 0x1D0FFFF8.
If --ejtag-addr is omitted (and not auto-detected from ELF), no DEVCFG0 patch is applied.
XC32 tool paths resolved via XC32_PATH env var (points to bin/ directory).
"""

import argparse
import os
import re
import sys

from rich.console import Console

END_RECORD = ":00000001FF"

_APP_HEX_FILL_START = 0x1D010200
_APP_HEX_FILL_END = 0x1D0FFFFC
_APP_HEX_CROP_END = 0x1D100000
_APP_SIGNATURE_ADDR = 0x1D0FFFF8

_con = Console(highlight=False)
_err = Console(stderr=True, highlight=False)


def _verbose_print(verbose: bool, message: str) -> None:
    if verbose:
        _con.print(message, markup=False)


def _fail(message: str) -> None:
    _err.print(f"[red][ERROR][/red] {message}")
    sys.exit(1)


# --- Linker script parsing ---------------------------------------------------

_LD_MEMORY_BLOCK_RE = re.compile(r"MEMORY\s*\{([^}]*)\}", re.DOTALL | re.IGNORECASE)
_LD_REGION_RE = re.compile(
    r"^\s*(\w+)\s*(?:\([^)]*\))?\s*:\s*ORIGIN\s*=\s*(0x[0-9A-Fa-f]+|\d+)",
    re.MULTILINE | re.IGNORECASE,
)

# Region name patterns for auto-detection (lowercase match)
_EJTAG_REGION_NAMES = {"config0", "devcfg0"}
_SIG_REGION_KEYWORD = "sig"


def _to_physical(addr: int) -> int:
    """Strip MIPS kseg0/kseg1 mapping bits → physical address."""
    return addr & 0x1FFFFFFF if addr >= 0x80000000 else addr


def parse_ld_memory(ld_path: str) -> dict[str, int]:
    """Parse MEMORY block from *ld_path*, return ``{region_name_lower: physical_addr}``."""
    with open(ld_path, "r", encoding="utf-8") as f:
        content = f.read()
    m = _LD_MEMORY_BLOCK_RE.search(content)
    if not m:
        return {}
    block = m.group(1)
    return {
        rm.group(1).lower(): _to_physical(int(rm.group(2), 0))
        for rm in _LD_REGION_RE.finditer(block)
    }


def detect_ejtag_addr(regions: dict[str, int]) -> int | None:
    """Return DEVCFG0 physical address from parsed LD regions, or None."""
    for name in _EJTAG_REGION_NAMES:
        if name in regions:
            return regions[name]
    return None


def detect_sig_addr(regions: dict[str, int]) -> int | None:
    """Return first region whose name contains 'sig', or None."""
    for name, addr in regions.items():
        if _SIG_REGION_KEYWORD in name:
            return addr
    return None


# PIC32 DEVCFG0 bit constants (architecture-level, same for all PIC32 devices):
# DEBUG[1:0] at bits 1:0 — 0b00 = debugger enabled, 0b11 = disabled
# JTAGEN     at bit  2   — 1    = JTAG enabled,      0    = disabled
_DEVCFG0_DEBUG_MASK = 0x00000003
_DEVCFG0_JTAGEN_BIT = 0x00000004


def _ihex_checksum(record_bytes: list[int]) -> int:
    return (~sum(record_bytes) + 1) & 0xFF


def _parse_ihex_record(line: str, line_no: int) -> tuple[int, int, int, bytes]:
    stripped = line.strip()
    if not stripped.startswith(":"):
        raise RuntimeError(f"line {line_no}: Intel HEX record must start with ':'")

    try:
        byte_count = int(stripped[1:3], 16)
        addr_offset = int(stripped[3:7], 16)
        record_type = int(stripped[7:9], 16)
    except ValueError as exc:
        raise RuntimeError(f"line {line_no}: invalid Intel HEX header") from exc

    expected_len = 11 + byte_count * 2
    if len(stripped) != expected_len:
        raise RuntimeError(
            f"line {line_no}: byte count expects {expected_len} characters, "
            f"got {len(stripped)}"
        )

    try:
        record_bytes = bytes.fromhex(stripped[1:])
    except ValueError as exc:
        raise RuntimeError(f"line {line_no}: invalid hexadecimal data") from exc

    if sum(record_bytes) & 0xFF:
        raise RuntimeError(f"line {line_no}: invalid Intel HEX checksum")

    data = record_bytes[4:-1]
    return byte_count, addr_offset, record_type, data


def validate_app_hex(app_path: str) -> None:
    """Validate that *app_path* is a bootloader-ready app Intel HEX image."""
    if not os.path.exists(app_path):
        raise RuntimeError(f"app HEX not found: {app_path}")

    with open(app_path, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\r\n") for line in f]

    if not lines:
        raise RuntimeError("app HEX is empty")

    current_ela = 0
    eof_seen = False
    min_addr: int | None = None
    max_addr: int | None = None
    data_records = 0

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if eof_seen:
            raise RuntimeError(f"line {line_no}: data found after end-of-file record")

        byte_count, addr_offset, record_type, data = _parse_ihex_record(line, line_no)

        if record_type == 0x00:
            if byte_count == 0:
                continue
            base_addr = (current_ela << 16) | addr_offset
            end_addr = base_addr + byte_count
            if base_addr < _APP_HEX_FILL_START or end_addr > _APP_HEX_CROP_END:
                raise RuntimeError(
                    f"line {line_no}: app data range 0x{base_addr:08X}-0x{end_addr - 1:08X} "
                    f"is outside prepared merge window 0x{_APP_HEX_FILL_START:08X}-"
                    f"0x{_APP_HEX_CROP_END - 1:08X}"
                )
            min_addr = base_addr if min_addr is None else min(min_addr, base_addr)
            max_addr = end_addr if max_addr is None else max(max_addr, end_addr)
            data_records += 1
        elif record_type == 0x01:
            if byte_count != 0 or addr_offset != 0:
                raise RuntimeError(f"line {line_no}: malformed end-of-file record")
            eof_seen = True
        elif record_type == 0x04:
            if byte_count != 2 or addr_offset != 0:
                raise RuntimeError(
                    f"line {line_no}: malformed extended linear address record"
                )
            current_ela = int.from_bytes(data, "big")
        else:
            raise RuntimeError(
                f"line {line_no}: unsupported Intel HEX record type 0x{record_type:02X}"
            )

    if not eof_seen:
        raise RuntimeError("app HEX is missing the end-of-file record")
    if data_records == 0 or min_addr is None or max_addr is None:
        raise RuntimeError("app HEX contains no data records")
    if min_addr != _APP_HEX_FILL_START or max_addr < _APP_HEX_FILL_END:
        raise RuntimeError(
            "app HEX does not look post-processed for bootloader merge; "
            f"expected filled/cropped coverage from 0x{_APP_HEX_FILL_START:08X} "
            f"through at least 0x{_APP_HEX_FILL_END - 1:08X}, got "
            f"0x{min_addr:08X}-0x{max_addr - 1:08X}"
        )


def _patch_word(lines: list[str], addr: int, word: int) -> list[str]:
    """Write *word* (little-endian, 4 bytes) at physical *addr* in an Intel HEX line list."""
    word_bytes = [(word >> (8 * i)) & 0xFF for i in range(4)]

    current_ela = 0
    result: list[str] = []
    patched = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(":"):
            result.append(line)
            continue

        byte_count = int(stripped[1:3], 16)
        addr_offset = int(stripped[3:7], 16)
        record_type = int(stripped[7:9], 16)
        data_hex = stripped[9 : 9 + byte_count * 2]

        if record_type == 0x04:
            current_ela = int(data_hex, 16)
            result.append(line)
            continue

        if record_type != 0x00:
            result.append(line)
            continue

        base_addr = (current_ela << 16) | addr_offset
        end_addr = base_addr + byte_count

        if base_addr <= addr < end_addr:
            data = bytearray.fromhex(data_hex)
            off = addr - base_addr
            for i in range(4):
                if off + i < byte_count:
                    data[off + i] = word_bytes[i]

            core = [
                byte_count,
                (addr_offset >> 8) & 0xFF,
                addr_offset & 0xFF,
                0x00,
            ] + list(data)
            chk = _ihex_checksum(core)
            result.append(
                f":{byte_count:02X}{addr_offset:04X}00{data.hex().upper()}{chk:02X}"
            )
            patched = True
        else:
            result.append(line)

    if not patched:
        # Address falls in blank flash (no existing record). Insert a new record
        # before the end-of-file record so the word lands in the output image.
        ela_high = (addr >> 16) & 0xFFFF
        addr_off = addr & 0xFFFF

        ela_core = [2, 0, 0, 4, (ela_high >> 8) & 0xFF, ela_high & 0xFF]
        ela_chk = _ihex_checksum(ela_core)
        ela_rec = f":02000004{ela_high:04X}{ela_chk:02X}"

        data = bytearray(word_bytes)
        dat_core = [4, (addr_off >> 8) & 0xFF, addr_off & 0xFF, 0x00] + list(data)
        dat_chk = _ihex_checksum(dat_core)
        dat_rec = f":04{addr_off:04X}00{data.hex().upper()}{dat_chk:02X}"

        # Insert before the end-of-file record
        eof_idx = next(
            (i for i, l in enumerate(result) if l.strip().upper() == END_RECORD),
            len(result),
        )
        result[eof_idx:eof_idx] = [ela_rec, dat_rec]

    return result


def _patch_devcfg0_ejtag(
    lines: list[str], devcfg0_addr: int, verbose: bool = False
) -> list[str]:
    """Enable EJTAG in the DEVCFG0 config word at *devcfg0_addr*.

    Clears DEBUG[1:0] (bits 1:0) and sets JTAGEN (bit 2).
    Without this patch the debugger attach fails with error 0x104 when
    the bootloader was built with JTAGEN=OFF and DEBUG=OFF.
    """
    current_ela = 0
    result: list[str] = []
    patched = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(":"):
            result.append(line)
            continue

        byte_count = int(stripped[1:3], 16)
        addr_offset = int(stripped[3:7], 16)
        record_type = int(stripped[7:9], 16)
        data_hex = stripped[9 : 9 + byte_count * 2]

        if record_type == 0x04:
            current_ela = int(data_hex, 16)
            result.append(line)
            continue

        if record_type != 0x00:
            result.append(line)
            continue

        base_addr = (current_ela << 16) | addr_offset
        end_addr = base_addr + byte_count

        if base_addr <= devcfg0_addr < end_addr:
            data = bytearray.fromhex(data_hex)
            off = devcfg0_addr - base_addr

            word = (
                data[off]
                | (data[off + 1] << 8)
                | (data[off + 2] << 16)
                | (data[off + 3] << 24)
            )
            orig = word
            word &= ~_DEVCFG0_DEBUG_MASK
            word |= _DEVCFG0_JTAGEN_BIT

            for i in range(4):
                data[off + i] = (word >> (8 * i)) & 0xFF

            core = [
                byte_count,
                (addr_offset >> 8) & 0xFF,
                addr_offset & 0xFF,
                0x00,
            ] + list(data)
            chk = _ihex_checksum(core)
            result.append(
                f":{byte_count:02X}{addr_offset:04X}00{data.hex().upper()}{chk:02X}"
            )
            patched = True

            _verbose_print(
                verbose,
                f"[merge_hex] DEVCFG0 : 0x{orig:08X} → 0x{word:08X}  "
                f"(JTAGEN=ON, DEBUG=ON) at phys 0x{devcfg0_addr:08X}",
            )
        else:
            result.append(line)

    if not patched:
        raise RuntimeError(
            f"DEVCFG0 at 0x{devcfg0_addr:08X} not found. "
            "The bootloader HEX must include config word records."
        )

    return result


def merge(
    boot_path: str,
    app_path: str,
    out_path: str,
    sig_addr: int | None = None,
    sig_word: int = 0x00000000,
    ejtag_addr: int | None = None,
    verbose: bool = False,
) -> None:
    if not os.path.exists(boot_path):
        _fail(f"bootloader HEX not found: {boot_path}")
    if not os.path.exists(app_path):
        _fail(f"app HEX not found: {app_path}")

    with open(boot_path, "r", encoding="utf-8") as f:
        boot_lines = [l.rstrip("\r\n") for l in f]

    with open(app_path, "r", encoding="utf-8") as f:
        app_lines = [l.rstrip("\r\n") for l in f]

    boot_stripped = [l for l in boot_lines if l.upper().strip() != END_RECORD]
    merged = boot_stripped + app_lines

    if sig_addr is not None:
        merged = _patch_word(merged, sig_addr, sig_word)
        _verbose_print(
            verbose,
            f"[merge_hex] signed  : 0x{sig_word:08X} written at phys 0x{sig_addr:08X}",
        )

    if ejtag_addr is not None:
        merged = _patch_devcfg0_ejtag(merged, ejtag_addr, verbose=verbose)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="\n", encoding="utf-8") as f:
        for line in merged:
            f.write(line + "\n")

    _verbose_print(
        verbose, f"[merge_hex] boot    : {boot_path}  ({len(boot_stripped)} records)"
    )
    _verbose_print(
        verbose, f"[merge_hex] app     : {app_path}  ({len(app_lines)} records)"
    )
    _verbose_print(
        verbose, f"[merge_hex] output  : {out_path}  ({len(merged)} records total)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge bootloader + app HEX and optionally patch signature/debug config bits."
    )
    parser.add_argument("boot", nargs="?", default=None, help="Bootloader HEX file")
    parser.add_argument("app", nargs="?", default=None, help="App HEX file")
    parser.add_argument("out", nargs="?", default=None, help="Output merged HEX file")
    parser.add_argument(
        "--boot-elf",
        default=None,
        metavar="FILE",
        help="Bootloader ELF — auto-generates .hex if absent, auto-detects --ejtag-addr.",
    )
    parser.add_argument(
        "--app-hex",
        default=None,
        metavar="FILE",
        help="App HEX already post-processed with srec_cat fill/crop for bootloader merge.",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="FILE",
        dest="output",
        help="Output merged HEX file (named alternative to positional out).",
    )
    parser.add_argument(
        "--sig-addr",
        type=lambda x: int(x, 0),
        default=None,
        metavar="ADDR",
        help="Physical address for signature word patch (e.g. 0x1D0FFFF8). Omit to skip.",
    )
    parser.add_argument(
        "--sig-word",
        type=lambda x: int(x, 0),
        default=0x00000000,
        metavar="VALUE",
        help="Signature word value (default: 0x00000000)",
    )
    parser.add_argument(
        "--ejtag-addr",
        type=lambda x: int(x, 0),
        default=None,
        metavar="ADDR",
        help="Physical address of DEVCFG0 for EJTAG enable (e.g. 0x1FC03FCC). Omit to skip.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable detailed merge diagnostics.",
    )
    args = parser.parse_args()

    from microchip_devtools.xc32.elf_utils import (
        detect_devcfg0_from_elf,
        ensure_hex,
    )

    # --- ELF/HEX-first resolution -------------------------------------------
    if args.boot_elf:
        args.boot = ensure_hex(args.boot_elf)
        if args.ejtag_addr is None:
            args.ejtag_addr = detect_devcfg0_from_elf(args.boot_elf)
            if args.ejtag_addr is not None:
                _verbose_print(
                    args.verbose,
                    f"[merge_hex] auto ejtag-addr: 0x{args.ejtag_addr:08X}  (from ELF sections)",
                )

    if args.app_hex:
        args.app = args.app_hex
        if args.sig_addr is None:
            args.sig_addr = _APP_SIGNATURE_ADDR
            _verbose_print(
                args.verbose,
                f"[merge_hex] auto sig-addr  : 0x{args.sig_addr:08X}  "
                "(app HEX bootloader signature)",
            )

    # Named -o / --output overrides positional out
    if args.output is not None:
        args.out = args.output

    # --- Validate required args ---------------------------------------------
    missing = [
        name
        for name, val in (("boot", args.boot), ("app", args.app), ("out", args.out))
        if not val
    ]
    if missing:
        parser.error(
            f"Missing required argument(s): {', '.join(missing)}.\n"
            "Provide positional boot/app/out or use --boot-elf/--app-hex/-o."
        )

    try:
        if args.app_hex:
            validate_app_hex(args.app)
        merge(
            args.boot,
            args.app,
            args.out,
            sig_addr=args.sig_addr,
            sig_word=args.sig_word,
            ejtag_addr=args.ejtag_addr,
            verbose=args.verbose,
        )
    except RuntimeError as exc:
        _fail(str(exc))


if __name__ == "__main__":
    main()
