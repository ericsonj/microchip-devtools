"""Tests for Intel HEX merge and patching logic."""

import os
import sys
import pytest
from microchip_devtools.xc32.elf_utils import (
    detect_devcfg0_from_elf,
    ensure_hex,
    parse_elf_config_sections,
)
from microchip_devtools.xc32.merge_hex import _ihex_checksum, _patch_word, merge, main

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "pic32mk_idu")
BOOT_ELF = os.path.join(FIXTURES, "boot.elf")
APP_ELF  = os.path.join(FIXTURES, "app.elf")


# --- HEX patching unit tests --------------------------------------------------

def _make_data_record(base_addr: int, data: bytes) -> str:
    ela_high = (base_addr >> 16) & 0xFFFF
    offset = base_addr & 0xFFFF
    ela_core = [2, 0, 0, 4, (ela_high >> 8) & 0xFF, ela_high & 0xFF]
    ela_chk = _ihex_checksum(ela_core)
    ela = f":02000004{ela_high:04X}{ela_chk:02X}"
    n = len(data)
    core = [n, (offset >> 8) & 0xFF, offset & 0xFF, 0x00] + list(data)
    chk = _ihex_checksum(core)
    rec = f":{n:02X}{offset:04X}00{data.hex().upper()}{chk:02X}"
    return f"{ela}\n{rec}"


def test_patch_word_writes_little_endian():
    addr = 0x1D0FFFF8
    lines = _make_data_record(addr - 4, bytes([0xFF] * 8)).splitlines()
    lines.append(":00000001FF")
    patched = _patch_word(lines, addr, 0x00000000)
    data_line = [l for l in patched if l.startswith(":") and l[7:9] == "00"][-1]
    data_bytes = bytes.fromhex(data_line[9: 9 + int(data_line[1:3], 16) * 2])
    off = addr - (addr - 4)
    assert data_bytes[off: off + 4] == b"\x00\x00\x00\x00"


def test_patch_word_inserts_record_when_address_in_blank_flash():
    lines = [":00000001FF"]
    result = _patch_word(lines, 0x1D0FFFF8, 0xDEADBEEF)
    assert result[-1].strip() == ":00000001FF"
    data_rec = next(r for r in result if r.startswith(":04"))
    data_bytes = bytes.fromhex(data_rec[9: 9 + 8])
    assert data_bytes == (0xDEADBEEF).to_bytes(4, "little")


def test_checksum_correctness():
    core = [2, 0, 0, 4, 0x00, 0x00]
    assert _ihex_checksum(core) == 0xFA


# --- ELF parsing unit tests ---------------------------------------------------

def test_parse_elf_config_sections_finds_devcfg0_section():
    sections = parse_elf_config_sections(BOOT_ELF)
    assert ".config_BFC03FCC" in sections
    assert sections[".config_BFC03FCC"] == 0x1FC03FCC


def test_parse_elf_config_sections_converts_virtual_to_physical():
    sections = parse_elf_config_sections(BOOT_ELF)
    for phys in sections.values():
        assert phys < 0x80000000, f"address 0x{phys:08X} not converted to physical"


def test_detect_devcfg0_from_boot_elf():
    assert detect_devcfg0_from_elf(BOOT_ELF) == 0x1FC03FCC


def test_ensure_hex_returns_existing_sibling(tmp_path):
    fake_elf = tmp_path / "fw.elf"
    fake_elf.write_bytes(b"\x00")
    sibling = tmp_path / "fw.hex"
    sibling.write_text(":00000001FF\n")
    assert ensure_hex(str(fake_elf)) == str(sibling)


# --- Integration: ELF-first full pipeline -------------------------------------

def test_merge_via_boot_elf_and_app_elf(tmp_path):
    """Full pipeline: boot.elf + app.elf → auto-detect DEVCFG0 → merged.hex."""
    out = str(tmp_path / "merged.hex")

    # Simulate: merge-hex --boot-elf boot.elf --app-elf app.elf -o merged.hex
    sys.argv = ["merge-hex", "--boot-elf", BOOT_ELF, "--app-elf", APP_ELF, "-o", out]
    main()

    with open(out, encoding="utf-8") as f:
        lines = f.readlines()

    assert lines[-1].strip() == ":00000001FF"
    assert len(lines) > 1000

    # Verify DEVCFG0 was patched: DEBUG[1:0]=0, JTAGEN=1 at 0x1FC03FCC
    target = 0x1FC03FCC
    current_ela = 0
    for line in lines:
        s = line.strip()
        if not s.startswith(":"):
            continue
        rec_type = int(s[7:9], 16)
        if rec_type == 0x04:
            current_ela = int(s[9:13], 16)
        elif rec_type == 0x00:
            off = int(s[3:7], 16)
            count = int(s[1:3], 16)
            base = (current_ela << 16) | off
            if base <= target < base + count:
                data = bytes.fromhex(s[9: 9 + count * 2])
                word = int.from_bytes(data[target - base: target - base + 4], "little")
                assert word & 0x3 == 0, f"DEBUG bits not cleared: 0x{word:08X}"
                assert word & 0x4 != 0, f"JTAGEN not set: 0x{word:08X}"
                return

    pytest.fail("DEVCFG0 record not found in merged HEX")
