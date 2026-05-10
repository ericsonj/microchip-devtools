"""Tests for XC32 fmt=3 detection logic."""

import os
import struct
import sys

import pytest

from microchip_devtools.xc32.validate_fmt3 import _is_fmt3_trigger, find_objects, main, scan_elf


# ---------------------------------------------------------------------------
# ELF32 builder
# ---------------------------------------------------------------------------

def _build_elf32(sym_name: str, sym_data: bytes, sym_addr: int = 0) -> bytes:
    """Return a minimal ELF32 relocatable with one initialized data symbol."""
    SHT_NULL, SHT_PROGBITS, SHT_SYMTAB, SHT_STRTAB = 0, 1, 2, 3
    SHF_ALLOC, SHF_WRITE = 0x2, 0x1
    STT_OBJECT, STB_GLOBAL = 1, 1

    # Section-name string table
    shstrtab = b"\x00.data\x00.strtab\x00.symtab\x00.shstrtab\x00"
    # Byte offsets within shstrtab:
    _n_data, _n_strtab, _n_symtab, _n_shstrtab = 1, 7, 15, 23

    # Symbol string table: null byte + name
    strtab = b"\x00" + sym_name.encode() + b"\x00"

    # Symbol table: null entry + our symbol
    sym_null  = struct.pack("<IIIBBH", 0, 0, 0, 0, 0, 0)
    st_info   = (STB_GLOBAL << 4) | STT_OBJECT
    sym_entry = struct.pack("<IIIBBH", 1, sym_addr, len(sym_data), st_info, 0, 1)
    symtab    = sym_null + sym_entry

    ehdr_size  = 52
    shentsize  = 40
    shnum      = 5   # null, .data, .strtab, .symtab, .shstrtab
    shstrndx   = 4

    # Offsets of each blob
    data_off    = ehdr_size
    strtab_off  = data_off   + len(sym_data)
    symtab_off  = strtab_off + len(strtab)
    shstrtab_off = symtab_off + len(symtab)
    shoff_raw   = shstrtab_off + len(shstrtab)
    shoff       = (shoff_raw + 3) & ~3   # align to 4

    e_ident = b"\x7fELF\x01\x01\x01" + b"\x00" * 9
    e_rest  = struct.pack("<HHIIIIIHHHHHH",
        1,          # ET_REL
        0x08,       # EM_MIPS
        1,          # EV_CURRENT
        0, 0,       # entry, phoff
        shoff,
        0,          # flags
        ehdr_size,
        0, 0,       # phentsize, phnum
        shentsize,
        shnum,
        shstrndx,
    )

    def shdr(ni, ty, fl, addr, off, sz, lnk, info, algn, esz):
        return struct.pack("<10I", ni, ty, fl, addr, off, sz, lnk, info, algn, esz)

    shdrs = (
        shdr(0,          SHT_NULL,     0,                  0, 0,           0,           0, 0, 0,  0),
        shdr(_n_data,    SHT_PROGBITS, SHF_ALLOC|SHF_WRITE, sym_addr, data_off,  len(sym_data), 0, 0, 4,  0),
        shdr(_n_strtab,  SHT_STRTAB,  0,                  0, strtab_off,  len(strtab),  0, 0, 1,  0),
        shdr(_n_symtab,  SHT_SYMTAB,  0,                  0, symtab_off,  len(symtab),  2, 0, 4, 16),
        shdr(_n_shstrtab,SHT_STRTAB,  0,                  0, shstrtab_off,len(shstrtab),0, 0, 1,  0),
    )

    body    = sym_data + strtab + symtab + shstrtab
    padding = b"\x00" * (shoff - (ehdr_size + len(body)))
    return e_ident + e_rest + body + padding + b"".join(shdrs)


def _write_elf(tmp_path, name, sym_name, sym_data, sym_addr=0, suffix=".o"):
    p = tmp_path / (name + suffix)
    p.write_bytes(_build_elf32(sym_name, sym_data, sym_addr))
    return str(p)


# ---------------------------------------------------------------------------
# _is_fmt3_trigger — unit tests
# ---------------------------------------------------------------------------

def test_all_zeros_not_fmt3():
    assert _is_fmt3_trigger(bytes([0x00] * 8)) is False


def test_uniform_nonzero_aligned_is_fmt3():
    data = bytes([0xAB, 0xCD, 0xEF, 0x12] * 4)
    assert _is_fmt3_trigger(data) is True


def test_uniform_nonzero_unaligned_is_fmt3():
    # 5 bytes: not divisible by 4 — this is the dangerous case
    data = bytes([0x01, 0x00, 0x00, 0x00, 0x01])
    assert _is_fmt3_trigger(data) is True


def test_non_uniform_bytes_not_fmt3():
    data = bytes([0x01, 0x02, 0x03, 0x04, 0x01, 0x02, 0x03, 0x05])
    assert _is_fmt3_trigger(data) is False


def test_too_short_not_fmt3():
    assert _is_fmt3_trigger(bytes([0xFF, 0xFF, 0xFF])) is False


def test_single_nonzero_word_is_fmt3():
    data = bytes([0xDE, 0xAD, 0xBE, 0xEF])
    assert _is_fmt3_trigger(data) is True


# ---------------------------------------------------------------------------
# scan_elf — unit tests
# ---------------------------------------------------------------------------

def test_scan_elf_no_violation_aligned(tmp_path):
    # fmt=3 pattern but size divisible by 4 → no violation
    data = bytes([0x01, 0x02, 0x03, 0x04] * 4)   # 16 bytes, 16 % 4 == 0
    path = _write_elf(tmp_path, "safe", "g_safe", data)
    assert scan_elf(path) == []


def test_scan_elf_violation_unaligned(tmp_path):
    # fmt=3 pattern AND size % 4 != 0 → violation
    data = bytes([0x01, 0x00, 0x00, 0x00] * 2 + [0x01])   # 9 bytes
    path = _write_elf(tmp_path, "bad", "g_bad", data)
    violations = scan_elf(path)
    assert len(violations) == 1
    v = violations[0]
    assert v["name"] == "g_bad"
    assert v["size"] == 9
    assert v["section"] == ".data"


def test_scan_elf_all_zeros_no_violation(tmp_path):
    data = bytes([0x00] * 8)
    path = _write_elf(tmp_path, "zeros", "g_zeros", data)
    assert scan_elf(path) == []


def test_scan_elf_non_uniform_no_violation(tmp_path):
    data = bytes([0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08])
    path = _write_elf(tmp_path, "varied", "g_varied", data)
    assert scan_elf(path) == []


def test_scan_elf_not_elf_returns_empty(tmp_path):
    p = tmp_path / "not_an_elf.o"
    p.write_bytes(b"not an elf file")
    assert scan_elf(str(p)) == []


def test_scan_elf_violation_fill_word(tmp_path):
    fill = bytes([0xDE, 0xAD, 0xBE, 0xEF])
    data = fill * 2 + fill[:1]   # 9 bytes, fmt=3, 9 % 4 != 0
    path = _write_elf(tmp_path, "fill", "g_fill", data)
    violations = scan_elf(path)
    assert len(violations) == 1
    assert violations[0]["fill_word"] == 0xEFBEADDE   # little-endian


def test_scan_elf_sym_too_small_ignored(tmp_path):
    # Symbol smaller than MIN_SYM_SIZE (4) → skipped even if fmt=3-ish
    data = bytes([0x01, 0x02, 0x03])
    path = _write_elf(tmp_path, "tiny", "g_tiny", data)
    assert scan_elf(path) == []


# ---------------------------------------------------------------------------
# find_objects — unit tests
# ---------------------------------------------------------------------------

def test_find_objects_yields_only_o_files(tmp_path):
    (tmp_path / "a.o").write_bytes(b"")
    (tmp_path / "b.o").write_bytes(b"")
    (tmp_path / "c.c").write_bytes(b"")
    (tmp_path / "d.elf").write_bytes(b"")
    found = set(find_objects(str(tmp_path)))
    assert found == {str(tmp_path / "a.o"), str(tmp_path / "b.o")}


def test_find_objects_recurses(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "x.o").write_bytes(b"")
    assert str(sub / "x.o") in set(find_objects(str(tmp_path)))


def test_find_objects_empty_dir(tmp_path):
    assert list(find_objects(str(tmp_path))) == []


# ---------------------------------------------------------------------------
# main() — CLI tests
# ---------------------------------------------------------------------------

def test_main_no_args_exits_1():
    sys.argv = ["validate-fmt3"]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_clean_file_exits_0(tmp_path):
    data = bytes([0x01, 0x02, 0x03, 0x04] * 4)   # aligned, no violation
    path = _write_elf(tmp_path, "ok", "g_ok", data)
    sys.argv = ["validate-fmt3", path]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_main_violation_exits_1(tmp_path, capsys):
    data = bytes([0x01, 0x00, 0x00, 0x00] * 2 + [0x01])   # 9 bytes, violation
    path = _write_elf(tmp_path, "bad", "g_bad", data)
    sys.argv = ["validate-fmt3", path]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "g_bad" in out
    assert "fmt=3" in out


def test_main_objects_dir_no_violations_exits_0(tmp_path):
    data = bytes([0x01, 0x02, 0x03, 0x04] * 4)
    _write_elf(tmp_path, "ok1", "g_ok1", data)
    _write_elf(tmp_path, "ok2", "g_ok2", data)
    sys.argv = ["validate-fmt3", "--objects-dir", str(tmp_path)]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_main_objects_dir_with_violation_exits_1(tmp_path, capsys):
    good = bytes([0x01, 0x02, 0x03, 0x04] * 4)
    bad  = bytes([0xFF, 0x00, 0x00, 0x00] * 2 + [0xFF])   # 9 bytes
    _write_elf(tmp_path, "good", "g_good", good)
    _write_elf(tmp_path, "bad",  "g_bad",  bad)
    sys.argv = ["validate-fmt3", "--objects-dir", str(tmp_path)]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "g_bad" in out


def test_main_objects_dir_empty_exits_0(tmp_path, capsys):
    sys.argv = ["validate-fmt3", "--objects-dir", str(tmp_path)]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_main_objects_dir_missing_path_arg_exits_1(capsys):
    sys.argv = ["validate-fmt3", "--objects-dir"]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
