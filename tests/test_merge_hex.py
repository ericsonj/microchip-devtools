"""Tests for Intel HEX merge and patching logic."""

import pytest
from voltu_devtools.xc32.merge_hex import _ihex_checksum, _patch_word


def _make_data_record(base_addr: int, data: bytes) -> str:
    ela_high = (base_addr >> 16) & 0xFFFF
    offset = base_addr & 0xFFFF
    ela_data = [(ela_high >> 8) & 0xFF, ela_high & 0xFF]
    ela_core = [2, 0, 0, 4] + ela_data
    ela_chk = _ihex_checksum(ela_core)
    ela = f":02000004{ela_high:04X}{ela_chk:02X}"

    n = len(data)
    core = [n, (offset >> 8) & 0xFF, offset & 0xFF, 0x00] + list(data)
    chk = _ihex_checksum(core)
    rec = f":{n:02X}{offset:04X}00{data.hex().upper()}{chk:02X}"
    return f"{ela}\n{rec}"


def test_patch_word_writes_little_endian():
    addr = 0x1D0FFFF8
    original_data = bytes([0xFF] * 8)
    lines = _make_data_record(addr - 4, original_data).splitlines()
    lines.append(":00000001FF")

    patched = _patch_word(lines, addr, 0x00000000)

    data_line = [l for l in patched if l.startswith(":") and l[7:9] == "00"][-1]
    data_bytes = bytes.fromhex(data_line[9:9 + int(data_line[1:3], 16) * 2])
    off = addr - (addr - 4)
    assert data_bytes[off:off+4] == b"\x00\x00\x00\x00"


def test_patch_word_raises_if_address_not_found():
    lines = [":00000001FF"]
    with pytest.raises(RuntimeError, match="not found in merged HEX"):
        _patch_word(lines, 0xDEADBEEF, 0x12345678)


def test_checksum_correctness():
    # Standard Intel HEX example: :020000040000FA
    core = [2, 0, 0, 4, 0x00, 0x00]
    assert _ihex_checksum(core) == 0xFA
