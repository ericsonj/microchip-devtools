"""Tests for Intel HEX merge and patching logic."""

import os
import sys
import pytest
from microchip_devtools.xc32.elf_utils import (
    detect_devcfg0_from_elf,
    ensure_hex,
    parse_elf_config_sections,
)
from microchip_devtools.xc32.merge_hex import (
    _ihex_checksum,
    _patch_word,
    main,
    merge,
    validate_app_hex,
)

FIRMWARE_OUTPUTS = os.path.join(
    os.path.dirname(__file__), "fixtures", "firmware-outputs"
)
BOOTLOADER_ELF = os.path.join(FIRMWARE_OUTPUTS, "boot.elf")
APP_PREPARED_HEX = os.path.join(
    FIRMWARE_OUTPUTS,
    "app_prepared.hex",
)
EXPECTED_MERGED_HEX = os.path.join(
    FIRMWARE_OUTPUTS,
    "expected.hex",
)


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


def _make_hex(base_addr: int, data: bytes, include_eof: bool = True) -> str:
    text = _make_data_record(base_addr, data)
    if include_eof:
        text += "\n:00000001FF"
    return text + "\n"


def test_patch_word_writes_little_endian():
    addr = 0x1D0FFFF8
    lines = _make_data_record(addr - 4, bytes([0xFF] * 8)).splitlines()
    lines.append(":00000001FF")
    patched = _patch_word(lines, addr, 0x00000000)
    data_line = [l for l in patched if l.startswith(":") and l[7:9] == "00"][-1]
    data_bytes = bytes.fromhex(data_line[9 : 9 + int(data_line[1:3], 16) * 2])
    off = addr - (addr - 4)
    assert data_bytes[off : off + 4] == b"\x00\x00\x00\x00"


def test_patch_word_inserts_record_when_address_in_blank_flash():
    lines = [":00000001FF"]
    result = _patch_word(lines, 0x1D0FFFF8, 0xDEADBEEF)
    assert result[-1].strip() == ":00000001FF"
    data_rec = next(r for r in result if r.startswith(":04"))
    data_bytes = bytes.fromhex(data_rec[9 : 9 + 8])
    assert data_bytes == (0xDEADBEEF).to_bytes(4, "little")


def test_checksum_correctness():
    core = [2, 0, 0, 4, 0x00, 0x00]
    assert _ihex_checksum(core) == 0xFA


def test_validate_app_hex_accepts_prepared_fixture():
    validate_app_hex(APP_PREPARED_HEX)


def test_validate_app_hex_rejects_sparse_raw_like_hex(tmp_path):
    app_hex = tmp_path / "raw-app.hex"
    app_hex.write_text(_make_hex(0x1D010200, b"\xaa" * 16), encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not look post-processed"):
        validate_app_hex(str(app_hex))


def test_validate_app_hex_rejects_out_of_window_data(tmp_path):
    app_hex = tmp_path / "bad-range.hex"
    app_hex.write_text(_make_hex(0x1D0101E0, b"\xaa" * 16), encoding="utf-8")

    with pytest.raises(RuntimeError, match="outside prepared merge window"):
        validate_app_hex(str(app_hex))


def test_validate_app_hex_rejects_bad_checksum(tmp_path):
    app_hex = tmp_path / "bad-checksum.hex"
    app_hex.write_text(":020000041D01DD\n:00000001FF\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="checksum"):
        validate_app_hex(str(app_hex))


def test_validate_app_hex_rejects_missing_eof(tmp_path):
    app_hex = tmp_path / "missing-eof.hex"
    app_hex.write_text(
        _make_hex(0x1D010200, b"\xaa" * 16, include_eof=False), encoding="utf-8"
    )

    with pytest.raises(RuntimeError, match="missing the end-of-file"):
        validate_app_hex(str(app_hex))


# --- ELF parsing unit tests ---------------------------------------------------


def test_parse_elf_config_sections_finds_devcfg0_section():
    sections = parse_elf_config_sections(BOOTLOADER_ELF)
    assert ".config_BFC03FCC" in sections
    assert sections[".config_BFC03FCC"] == 0x1FC03FCC


def test_parse_elf_config_sections_converts_virtual_to_physical():
    sections = parse_elf_config_sections(BOOTLOADER_ELF)
    for phys in sections.values():
        assert phys < 0x80000000, f"address 0x{phys:08X} not converted to physical"


def test_detect_devcfg0_from_boot_elf():
    assert detect_devcfg0_from_elf(BOOTLOADER_ELF) == 0x1FC03FCC


def test_ensure_hex_returns_existing_sibling(tmp_path):
    fake_elf = tmp_path / "fw.elf"
    fake_elf.write_bytes(b"\x00")
    sibling = tmp_path / "fw.hex"
    sibling.write_text(":00000001FF\n")
    assert ensure_hex(str(fake_elf)) == str(sibling)


# --- Integration: ELF-first full pipeline -------------------------------------


def test_merge_via_boot_elf_and_app_hex(tmp_path):
    """Full pipeline: boot.elf + prepared app.hex -> auto-detect DEVCFG0."""
    out = str(tmp_path / "merged.hex")

    sys.argv = [
        "merge-hex",
        "--boot-elf",
        BOOTLOADER_ELF,
        "--app-hex",
        APP_PREPARED_HEX,
        "-o",
        out,
    ]
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
                data = bytes.fromhex(s[9 : 9 + count * 2])
                word = int.from_bytes(data[target - base : target - base + 4], "little")
                assert word & 0x3 == 0, f"DEBUG bits not cleared: 0x{word:08X}"
                assert word & 0x4 != 0, f"JTAGEN not set: 0x{word:08X}"
                return

    pytest.fail("DEVCFG0 record not found in merged HEX")


def test_merge_idu_firmware_outputs_match_expected_hex(tmp_path, monkeypatch):
    out = tmp_path / "PRG-IDU-0002_WITH_BOOTLOADER.hex"

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "merge-hex",
            "--boot-elf",
            BOOTLOADER_ELF,
            "--app-hex",
            APP_PREPARED_HEX,
            "-o",
            str(out),
        ],
    )
    main()

    with open(out, "rb") as actual, open(EXPECTED_MERGED_HEX, "rb") as expected:
        assert actual.read() == expected.read()


def test_merge_is_silent_by_default(tmp_path, capsys):
    boot = tmp_path / "boot.hex"
    app = tmp_path / "app.hex"
    out = tmp_path / "merged.hex"
    boot.write_text(":00000001FF\n", encoding="utf-8")
    app.write_text(":00000001FF\n", encoding="utf-8")

    merge(str(boot), str(app), str(out))

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_merge_verbose_prints_diagnostics(tmp_path, capsys):
    boot = tmp_path / "boot.hex"
    app = tmp_path / "app.hex"
    out = tmp_path / "merged.hex"
    boot.write_text(":00000001FF\n", encoding="utf-8")
    app.write_text(":00000001FF\n", encoding="utf-8")

    merge(str(boot), str(app), str(out), verbose=True)

    captured = capsys.readouterr()
    assert "[merge_hex] boot" in captured.out
    assert "[merge_hex] app" in captured.out
    assert "[merge_hex] output" in captured.out
