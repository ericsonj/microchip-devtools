#!/usr/bin/env python3
"""Detect initialized static variables that would trigger XC32 __dinit_copy_val_data bug.

XC32 selects fmt=3 when all array elements equal the same non-zero constant.
The fmt=3 handler (__dinit_copy_val_data) decrements nbytes by 4 per iteration
and exits only when nbytes == 0. If nbytes % 4 != 0 the counter wraps to
0xFFFFFFFC and the loop writes forever, corrupting all memory before crashing
with a Data Bus Error at an unmapped address.

The emulator build uses mipsel-linux-gnu-gcc and --gc-sections, so some
translation units are eliminated from the final ELF even though they ARE linked
in the real XC32 build. Scanning only the final ELF misses those. This script
scans individual object files (.o) where all symbols are present before GC.

Usage:
    mchp-validate-xc32 <elf_or_obj> [<elf_or_obj> ...]
    mchp-validate-xc32 --objects-dir <dir>

Exit codes:
    0  — no violations found
    1  — one or more XC32 fmt=3 risks detected (also exits 1 on parse error)
"""

import os
import struct
import sys

SHT_SYMTAB   = 2
SHT_STRTAB   = 3
SHT_PROGBITS = 1
SHF_ALLOC    = 0x2
SHF_WRITE    = 0x1
STT_OBJECT   = 1

MIN_SYM_SIZE = 4


def _read_shdr(f, endian, shoff, shentsize, idx):
    f.seek(shoff + idx * shentsize)
    raw = f.read(shentsize)
    if len(raw) < 40:
        return None
    sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, \
        sh_link, _info, _align, sh_entsize = \
        struct.unpack_from(f"{endian}10I", raw)
    return {
        "name_idx": sh_name,
        "type":     sh_type,
        "flags":    sh_flags,
        "addr":     sh_addr,
        "offset":   sh_offset,
        "size":     sh_size,
        "link":     sh_link,
        "entsize":  sh_entsize,
    }


def _section_name(f, shstrtab, name_idx):
    f.seek(shstrtab["offset"] + name_idx)
    buf = bytearray()
    while True:
        c = f.read(1)
        if not c or c == b"\x00":
            break
        buf.extend(c)
    return buf.decode("ascii", errors="replace")


def _read_cstr(data, offset):
    end = data.index(b"\x00", offset)
    return data[offset:end].decode("ascii", errors="replace")


def _is_fmt3_trigger(data):
    """True if XC32 would choose fmt=3: all bytes non-zero and bytes[0:4] repeated."""
    if len(data) < 4:
        return False
    if all(b == 0 for b in data):
        return False
    fill = data[0:4]
    for i in range(0, len(data), 4):
        chunk = data[i:i + 4]
        if chunk != fill[:len(chunk)]:
            return False
    return True


def scan_elf(path):
    """Scan one ELF32 file (.o or final ELF). Return list of violation dicts."""
    violations = []

    with open(path, "rb") as f:
        e_ident = f.read(16)
        if e_ident[:4] != b"\x7fELF" or e_ident[4] != 1:
            return violations

        endian = "<" if e_ident[5] == 1 else ">"
        hdr = f.read(36)
        e_shoff     = struct.unpack_from(f"{endian}I", hdr, 16)[0]
        e_shentsize = struct.unpack_from(f"{endian}H", hdr, 30)[0]
        e_shnum     = struct.unpack_from(f"{endian}H", hdr, 32)[0]
        e_shstrndx  = struct.unpack_from(f"{endian}H", hdr, 34)[0]

        if e_shoff == 0 or e_shnum == 0:
            return violations

        shdrs = []
        for i in range(e_shnum):
            sh = _read_shdr(f, endian, e_shoff, e_shentsize, i)
            if sh is None:
                return violations
            shdrs.append(sh)

        shstrtab = shdrs[e_shstrndx]
        for sh in shdrs:
            sh["name"] = _section_name(f, shstrtab, sh["name_idx"])

        symtab = next((s for s in shdrs if s["type"] == SHT_SYMTAB), None)
        if symtab is None:
            return violations

        strtab_sh = shdrs[symtab["link"]]
        f.seek(strtab_sh["offset"])
        strtab = f.read(strtab_sh["size"])

        data_sections = {}
        for idx, sh in enumerate(shdrs):
            if (sh["type"] == SHT_PROGBITS
                    and (sh["flags"] & SHF_ALLOC)
                    and (sh["flags"] & SHF_WRITE)
                    and sh["size"] > 0):
                f.seek(sh["offset"])
                data_sections[idx] = (sh, f.read(sh["size"]))

        sym_entsize = symtab["entsize"] or 16
        n_syms = symtab["size"] // sym_entsize
        f.seek(symtab["offset"])
        for _ in range(n_syms):
            raw = f.read(sym_entsize)
            st_name, st_value, st_size, st_info, _, st_shndx = \
                struct.unpack_from(f"{endian}IIIBBH", raw)

            if (st_info & 0x0F) != STT_OBJECT:
                continue
            if st_size < MIN_SYM_SIZE:
                continue
            if st_shndx not in data_sections:
                continue

            sh, sec_bytes = data_sections[st_shndx]
            offset = st_value - sh["addr"]
            if offset < 0 or offset + st_size > len(sec_bytes):
                continue

            sym_bytes = sec_bytes[offset:offset + st_size]
            if not _is_fmt3_trigger(sym_bytes):
                continue
            if st_size % 4 == 0:
                continue

            name = _read_cstr(strtab, st_name)
            fill_word = int.from_bytes(sym_bytes[:4], "little")
            violations.append({
                "file":      path,
                "name":      name,
                "size":      st_size,
                "fill_word": fill_word,
                "addr":      st_value,
                "section":   sh["name"],
            })

    return violations


def find_objects(root):
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.endswith(".o"):
                yield os.path.join(dirpath, fn)


def main():
    args = sys.argv[1:]
    if not args:
        print(f"Usage: {sys.argv[0]} <file.o|file.elf> [...] | --objects-dir <dir>",
              file=sys.stderr)
        sys.exit(1)

    paths = []
    if args[0] == "--objects-dir":
        if len(args) < 2:
            print("--objects-dir requires a path", file=sys.stderr)
            sys.exit(1)
        paths = list(find_objects(args[1]))
        if not paths:
            print("validate_xc32_fmt3: no .o files found under " + args[1])
            sys.exit(0)
    else:
        paths = args

    all_violations = []
    for p in paths:
        try:
            all_violations.extend(scan_elf(p))
        except (OSError, struct.error, ValueError) as e:
            print(f"validate_xc32_fmt3: warning: could not parse {p}: {e}",
                  file=sys.stderr)

    if not all_violations:
        sys.exit(0)

    for v in all_violations:
        leftover = v["size"] % 4
        print(
            f"ERROR: XC32 fmt=3 risk in '{os.path.basename(v['file'])}': "
            f"symbol '{v['name']}'\n"
            f"       size={v['size']} bytes  ({leftover} leftover after /4)  "
            f"fill_word=0x{v['fill_word']:08X}  "
            f"section={v['section']}\n"
            f"       __dinit_copy_val_data will loop forever on hardware.\n"
            f"       Fix: make sizeof({v['name']}) divisible by 4, "
            f"or use non-uniform init, or change to uint32_t."
        )

    print(f"\nvalidate_xc32_fmt3: FAIL — {len(all_violations)} violation(s) found")
    sys.exit(1)


if __name__ == "__main__":
    main()
