from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pymakelib import PhonyTarget


class MPLABProject:
    """Base class for PIC32/XC32 firmware projects using pymaketool.

    Subclass this and set class attributes to configure the project.
    All AbstractMake methods are pre-implemented with PIC32/XC32 defaults.
    Env vars (XC32_PATH, DFP_PATH, IPE_CMD, PROGRAMMER) are read from the
    shell environment with fallbacks from setup_env COMMON_DEFAULTS.

    Usage in pymake/Makefile.py::

        from pymakelib import Makeclass
        from microchip_devtools.mplab.project import MPLABProject

        @Makeclass
        class Project(MPLABProject):
            processor = "32MX795F512L"
            linker_script = "linker_script.ld"
            xc32_path = "/opt/microchip/xc32/v2.50"
            dfp_path = "/opt/microchip/xc32/v2.50/pic32mx/dfp
            target_elf = "build/firmware.elf"
            target_map = "build/firmware.map"
            target_memory_summary = "build/firmware.memsummary"
            target_hex = "build/firmware.hex"
            target_bin = "build/firmware.bin"
    """

    # Required — consumer must set
    processor: str = ""
    linker_script: str = ""
    xc32_path: str = ""
    dfp_path: str = ""
    target_elf: str = ""
    target_map: str = ""
    target_memory_summary: str = ""
    target_hex: str = ""
    target_bin: str = ""

    # ── AbstractMake interface ────────────────────────────────────────────
    def getCompilerSet(self, **kwargs) -> dict:
        """
        Return the compiler toolchain configuration.

        Uses the XC32 compiler toolchain for PIC32MK microcontrollers.
        Adjust XC32_PATH if the toolchain is installed in a different location.

        Returns:
            dict: Paths to compiler executables
        """
        xc32 = self.xc32_path
        prefix = xc32 + "xc32-"
        return {
            "CC": prefix + "gcc",
            "CXX": prefix + "g++",
            "LD": prefix + "gcc",
            "AR": prefix + "ar",
            "AS": prefix + "as",
            "OBJCOPY": prefix + "objcopy",
            "SIZE": prefix + "size",
            "OBJDUMP": prefix + "objdump",
            "NM": prefix + "nm",
            "STRIP": prefix + "strip",
            "READELF": prefix + "readelf",
            "INCLUDES": [
                xc32 + "../pic32mx/include",
                xc32 + "../pic32mx/include/musl",
                xc32 + "../pic32mx/include/pic32m-libs",
                xc32 + "../pic32mx/include/proc",
            ],
        }

    def getCompilerOpts(self, **kwargs) -> dict:
        """
        Return compiler options for the PIC32MK project.

        These options are extracted from the MPLAB X generated Makefile and
        include processor-specific flags, optimization settings, and FreeRTOS includes.

        Returns:
            dict: Compiler options grouped by category
        """
        return {
            "MACHINE-OPTS": [
                "-mprocessor=" + self.processor,
                "-mdfp=" + self.dfp_path,
            ],
            "OPTIMIZE-OPTS": ["-O1"],
            "OPTIONS": [
                "-g",
                "-xc",
                "-ffunction-sections",
                "-fdata-sections",
                "-fno-common",
            ],
            "PREPROCESSOR-OPTS": ["-MP", "-MMD"],
            "WARNINGS-OPTS": [],
            "CONTROL-C-OPTS": ["-c"],
            "GENERAL-OPTS": [],
        }

    def getLinkerOpts(self, **kwargs) -> dict:
        """
        Return linker options for the PIC32MK project.

        Includes the linker script and memory configuration options
        extracted from the MPLAB X generated Makefile.

        Returns:
            dict: Linker options grouped by category
        """
        return {
            "LINKER-SCRIPT": ["-T" + self.linker_script],
            "MACHINE-OPTS": [
                "-mprocessor=" + self.processor,
                "-mdfp=" + self.dfp_path,
            ],
            "GENERAL-OPTS": [],
            "LINKER-OPTS": [
                "-Wl,--defsym=__MPLAB_BUILD=1",
                "-Wl,--defsym=_min_heap_size=512",
                "-Wl,--gc-sections",
                "-Wl,--no-code-in-dinit",
                "-Wl,--no-dinit-in-serial-mem",
                "-Wl,--sort-section=name",
                "-Wl,-Map=" + self.target_map,
                "-Wl,--memorysummary," + self.target_memory_summary,
            ],
            "LIBRARIES": [],
        }

    def getTargetsScript(self, **kwargs) -> dict:
        from pymakelib import MKVARS  # noqa: PLC0415

        xc32 = self.xc32_path
        return {
            "TARGET": {
                "LOGKEY": "LD",
                "FILE": self.target_elf,
                "SCRIPT": [
                    "@mkdir -p $(dir $@) &&",
                    MKVARS.LD,
                    "-o",
                    "$@",
                    MKVARS.OBJECTS,
                    MKVARS.LDFLAGS,
                ],
            },
            "TARGET_HEX": {
                "LOGKEY": "HEX",
                "FILE": self.target_hex,
                "SCRIPT": [xc32 + "xc32-bin2hex", MKVARS.TARGET],
            },
            "TARGET_BIN": {
                "LOGKEY": "BIN",
                "FILE": self.target_bin,
                "SCRIPT": [
                    MKVARS.OBJCOPY,
                    "-O",
                    "binary",
                    MKVARS.TARGET,
                    self.target_bin,
                ],
            },
        }

    # ── Source ordering ───────────────────────────────────────────────────

    def mplab_walk(self, paths: list[Path], excluded: set[Path]) -> list[Path]:
        """Sort paths in MPLAB source order: dirs before files,
        case-insensitive alpha, depth-first."""
        kept = [p for p in paths if p.resolve() not in excluded]
        tree: dict = {}
        for p in kept:
            node = tree
            for part in p.parts[:-1]:
                child = node.get(part)
                if not isinstance(child, dict):
                    child = {}
                    node[part] = child
                node = child
            node[p.parts[-1]] = p

        def flatten(node: dict) -> list[Path]:
            dirs = sorted(
                (k for k, v in node.items() if isinstance(v, dict)), key=str.lower
            )
            files = sorted(
                (k for k, v in node.items() if not isinstance(v, dict)), key=str.lower
            )
            out: list[Path] = []
            for name in dirs:
                out.extend(flatten(node[name]))
            for name in files:
                out.append(node[name])
            return out

        return flatten(tree)

    def sort_sources(self, paths: list[Path]) -> list[Path]:
        return self.mplab_walk(paths, set())

    def sort_modules(self, paths: list[Path]) -> list[Path]:
        return self.mplab_walk(paths, set())
