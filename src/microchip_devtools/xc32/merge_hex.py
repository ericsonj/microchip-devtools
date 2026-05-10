#!/usr/bin/env python3
"""
microchip_devtools.xc32.merge_hex — Merge bootloader + app HEX into a single image.

Optionally patches:
  - A signature word at a given physical address (for bootloader app-valid checks)
  - DEVCFG0 config bits to enable EJTAG debugging (PIC32MK-specific)

Usage:
    merge-hex boot.hex app.hex out.hex [options]

Options:
    --sig-addr ADDR     Physical address to write the signature word (hex, e.g. 0x1D0FFFF8)
    --sig-word VALUE    Signature word value (hex, default: 0x00000000)
    --ejtag-addr ADDR   Physical address of DEVCFG0 config word for EJTAG enable (optional)

If --sig-addr is omitted, no signature patch is applied.
If --ejtag-addr is omitted, no DEVCFG0 patch is applied.
"""

import argparse
import os
import sys

END_RECORD = ":00000001FF"

# PIC32 DEVCFG0 bit constants (architecture-level, same for all PIC32 devices):
# DEBUG[1:0] at bits 1:0 — 0b00 = debugger enabled, 0b11 = disabled
# JTAGEN     at bit  2   — 1    = JTAG enabled,      0    = disabled
_DEVCFG0_DEBUG_MASK = 0x00000003
_DEVCFG0_JTAGEN_BIT = 0x00000004


def _ihex_checksum(record_bytes: list[int]) -> int:
    return (~sum(record_bytes) + 1) & 0xFF


def _patch_word(lines: list[str], addr: int, word: int) -> list[str]:
    """Write *word* (little-endian, 4 bytes) at physical *addr* in an Intel HEX line list."""
    word_bytes = [(word >> (8 * i)) & 0xFF for i in range(4)]

    current_ela = 0
    result: list[str] = []
    patched = False

    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(':'):
            result.append(line)
            continue

        byte_count  = int(stripped[1:3],   16)
        addr_offset = int(stripped[3:7],   16)
        record_type = int(stripped[7:9],   16)
        data_hex    = stripped[9: 9 + byte_count * 2]

        if record_type == 0x04:
            current_ela = int(data_hex, 16)
            result.append(line)
            continue

        if record_type != 0x00:
            result.append(line)
            continue

        base_addr = (current_ela << 16) | addr_offset
        end_addr  = base_addr + byte_count

        if base_addr <= addr < end_addr:
            data = bytearray.fromhex(data_hex)
            off  = addr - base_addr
            for i in range(4):
                if off + i < byte_count:
                    data[off + i] = word_bytes[i]

            core = [byte_count,
                    (addr_offset >> 8) & 0xFF,
                     addr_offset       & 0xFF,
                    0x00] + list(data)
            chk  = _ihex_checksum(core)
            result.append(f":{byte_count:02X}{addr_offset:04X}00{data.hex().upper()}{chk:02X}")
            patched = True
        else:
            result.append(line)

    if not patched:
        raise RuntimeError(
            f"[merge_hex] ERROR: address 0x{addr:08X} not found in merged HEX.\n"
            f"             Expected a data record covering that address."
        )

    return result


def _patch_devcfg0_ejtag(lines: list[str], devcfg0_addr: int) -> list[str]:
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
        if not stripped.startswith(':'):
            result.append(line)
            continue

        byte_count  = int(stripped[1:3],   16)
        addr_offset = int(stripped[3:7],   16)
        record_type = int(stripped[7:9],   16)
        data_hex    = stripped[9: 9 + byte_count * 2]

        if record_type == 0x04:
            current_ela = int(data_hex, 16)
            result.append(line)
            continue

        if record_type != 0x00:
            result.append(line)
            continue

        base_addr = (current_ela << 16) | addr_offset
        end_addr  = base_addr + byte_count

        if base_addr <= devcfg0_addr < end_addr:
            data = bytearray.fromhex(data_hex)
            off  = devcfg0_addr - base_addr

            word  = data[off] | (data[off+1] << 8) | (data[off+2] << 16) | (data[off+3] << 24)
            orig  = word
            word &= ~_DEVCFG0_DEBUG_MASK
            word |=  _DEVCFG0_JTAGEN_BIT

            for i in range(4):
                data[off + i] = (word >> (8 * i)) & 0xFF

            core = [byte_count,
                    (addr_offset >> 8) & 0xFF,
                     addr_offset       & 0xFF,
                    0x00] + list(data)
            chk  = _ihex_checksum(core)
            result.append(f":{byte_count:02X}{addr_offset:04X}00{data.hex().upper()}{chk:02X}")
            patched = True

            print(f"[merge_hex] DEVCFG0 : 0x{orig:08X} → 0x{word:08X}  "
                  f"(JTAGEN=ON, DEBUG=ON) at phys 0x{devcfg0_addr:08X}")
        else:
            result.append(line)

    if not patched:
        raise RuntimeError(
            f"[merge_hex] ERROR: DEVCFG0 at 0x{devcfg0_addr:08X} not found.\n"
            f"             The bootloader HEX must include config word records."
        )

    return result


def merge(
    boot_path: str,
    app_path: str,
    out_path: str,
    sig_addr: int | None = None,
    sig_word: int = 0x00000000,
    ejtag_addr: int | None = None,
) -> None:
    if not os.path.exists(boot_path):
        sys.exit(f"[merge_hex] ERROR: bootloader HEX not found: {boot_path}")
    if not os.path.exists(app_path):
        sys.exit(f"[merge_hex] ERROR: app HEX not found: {app_path}\n"
                 f"             Run 'make' first to build the app.")

    with open(boot_path, "r", encoding="utf-8") as f:
        boot_lines = [l.rstrip("\r\n") for l in f]

    with open(app_path, "r", encoding="utf-8") as f:
        app_lines = [l.rstrip("\r\n") for l in f]

    boot_stripped = [l for l in boot_lines if l.upper().strip() != END_RECORD]
    merged = boot_stripped + app_lines

    if sig_addr is not None:
        merged = _patch_word(merged, sig_addr, sig_word)
        print(f"[merge_hex] signed  : 0x{sig_word:08X} written at phys 0x{sig_addr:08X}")

    if ejtag_addr is not None:
        merged = _patch_devcfg0_ejtag(merged, ejtag_addr)

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", newline="\n", encoding="utf-8") as f:
        for line in merged:
            f.write(line + "\n")

    print(f"[merge_hex] boot    : {boot_path}  ({len(boot_stripped)} records)")
    print(f"[merge_hex] app     : {app_path}  ({len(app_lines)} records)")
    print(f"[merge_hex] output  : {out_path}  ({len(merged)} records total)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Merge bootloader + app HEX and optionally patch signature/debug config bits."
    )
    parser.add_argument("boot", help="Bootloader HEX file")
    parser.add_argument("app",  help="App HEX file")
    parser.add_argument("out",  help="Output merged HEX file")
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

    args = parser.parse_args()
    merge(args.boot, args.app, args.out,
          sig_addr=args.sig_addr, sig_word=args.sig_word, ejtag_addr=args.ejtag_addr)


if __name__ == "__main__":
    main()
