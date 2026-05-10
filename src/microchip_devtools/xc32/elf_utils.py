"""ELF utilities for XC32 toolchain integration.

Provides:
  - detect_devcfg0_from_elf  — find DEVCFG0 physical address from boot ELF section headers
  - ensure_hex               — return sibling .hex, generating it via xc32-bin2hex if absent
"""

import os
import struct
import subprocess
from pathlib import Path

# ELF section type constant
_SHT_PROGBITS = 1

# Known DEVCFG0 physical addresses across PIC32 families.
# The boot ELF contains .config_<HEX_ADDR> sections; the address embedded in the
# section name is matched against this set to identify which section is DEVCFG0.
_KNOWN_DEVCFG0_PHYS: set[int] = {
    0x1FC03FCC,  # PIC32MK  — primary config page
    0x1FC0FFCC,  # PIC32MZ
    0x1FC2FFCC,  # PIC32MM
}


def _xc32_tool(name: str) -> str:
    """Resolve an XC32 tool path using the XC32_PATH env var (points to bin/ dir)."""
    xc32_bin = os.environ.get("XC32_PATH", "")
    return os.path.join(xc32_bin, name) if xc32_bin else name


def _to_physical(addr: int) -> int:
    """Strip MIPS kseg0/kseg1 mapping bits → physical address."""
    return addr & 0x1FFFFFFF if addr >= 0x80000000 else addr


def _read_shdr(f, endian: str, shoff: int, shentsize: int, idx: int) -> dict | None:
    f.seek(shoff + idx * shentsize)
    raw = f.read(shentsize)
    if len(raw) < 40:
        return None
    sh_name, sh_type, _flags, sh_addr, sh_offset, sh_size, *_ = \
        struct.unpack_from(f"{endian}10I", raw)
    return {"name_idx": sh_name, "type": sh_type, "addr": sh_addr, "offset": sh_offset, "size": sh_size}


def _section_name(f, shstrtab: dict, name_idx: int) -> str:
    f.seek(shstrtab["offset"] + name_idx)
    buf = bytearray()
    while True:
        c = f.read(1)
        if not c or c == b"\x00":
            break
        buf.extend(c)
    return buf.decode("ascii", errors="replace")


def parse_elf_config_sections(elf_path: str) -> dict[str, int]:
    """Parse ELF32 section headers and return ``{section_name: physical_addr}``
    for all PROGBITS sections whose name starts with ``.config_``."""
    result: dict[str, int] = {}
    with open(elf_path, "rb") as f:
        e_ident = f.read(16)
        if e_ident[:4] != b"\x7fELF" or e_ident[4] != 1:
            return result

        endian = "<" if e_ident[5] == 1 else ">"
        hdr = f.read(36)
        e_shoff     = struct.unpack_from(f"{endian}I", hdr, 16)[0]
        e_shentsize = struct.unpack_from(f"{endian}H", hdr, 30)[0]
        e_shnum     = struct.unpack_from(f"{endian}H", hdr, 32)[0]
        e_shstrndx  = struct.unpack_from(f"{endian}H", hdr, 34)[0]

        if e_shoff == 0 or e_shnum == 0:
            return result

        shdrs = []
        for i in range(e_shnum):
            sh = _read_shdr(f, endian, e_shoff, e_shentsize, i)
            if sh is None:
                return result
            shdrs.append(sh)

        shstrtab = shdrs[e_shstrndx]
        for sh in shdrs:
            if sh["type"] != _SHT_PROGBITS:
                continue
            name = _section_name(f, shstrtab, sh["name_idx"])
            if name.startswith(".config_"):
                # XC32 may produce compound names like ".config_BFC03FCC.__config_BFC03FCC".
                # Normalize to the address-bearing prefix: ".config_<ADDR>".
                normalized = "." + name.lstrip(".").split(".")[0]
                result[normalized] = _to_physical(sh["addr"])

    return result


def detect_devcfg0_from_elf(elf_path: str) -> int | None:
    """Return the DEVCFG0 physical address found in *elf_path*'s section headers, or None.

    Scans ``.config_*`` PROGBITS sections and matches their physical address against
    a small table of known DEVCFG0 addresses across PIC32 families.
    """
    sections = parse_elf_config_sections(elf_path)
    for phys in sections.values():
        if phys in _KNOWN_DEVCFG0_PHYS:
            return phys
    return None


def ensure_hex(elf_path: str) -> str:
    """Return the HEX file path for *elf_path*.

    If a sibling ``.hex`` file exists (same directory, same stem), return it immediately.
    Otherwise invoke ``xc32-bin2hex`` (resolved via ``XC32_PATH`` env var) to generate it.

    Raises:
        RuntimeError: if xc32-bin2hex exits non-zero or fails to create the .hex file.
    """
    elf = Path(elf_path)
    hex_path = elf.with_suffix(".hex")
    if hex_path.exists():
        return str(hex_path)

    tool = _xc32_tool("xc32-bin2hex")
    result = subprocess.run(
        [tool, str(elf)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"[elf_utils] xc32-bin2hex failed (exit {result.returncode}):\n{result.stderr}"
        )
    if not hex_path.exists():
        raise RuntimeError(
            f"[elf_utils] xc32-bin2hex ran but {hex_path} was not created"
        )
    print(f"[elf_utils] generated : {hex_path}")
    return str(hex_path)
