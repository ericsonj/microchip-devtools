"""Individual prerequisite check functions for Voltu firmware projects."""

import shutil
import subprocess
import sys
from pathlib import Path

from microchip_devtools.setup_env._ui import (
    _fail, _pass, _warn, offer_save_to_env, prompt_path,
)
from microchip_devtools.setup_env.defaults import PROGRAMMER_VALUES


def check_python() -> bool:
    label = f"Python >= 3.10  (found {sys.version.split()[0]})"
    if sys.version_info >= (3, 10):
        _pass(label)
        return True
    _fail("Python >= 3.10", f"Found {sys.version.split()[0]}. Install Python 3.10 or newer.")
    return False


def check_poetry() -> bool:
    binary = shutil.which("poetry")
    if binary is None:
        _fail("Poetry", "Not found on PATH. Install from https://python-poetry.org/docs/")
        return False
    try:
        result = subprocess.run(
            ["poetry", "--version"], capture_output=True, text=True, timeout=10
        )
        version = result.stdout.strip() or result.stderr.strip()
        _pass(f"Poetry  ({version})")
        return True
    except Exception as exc:
        _fail("Poetry", str(exc))
        return False


def check_make() -> bool:
    binary = shutil.which("make")
    if binary is None:
        _fail("GNU Make", "Not found on PATH. Install with: sudo apt install make")
        return False
    try:
        result = subprocess.run(
            ["make", "--version"], capture_output=True, text=True, timeout=10
        )
        first_line = result.stdout.splitlines()[0] if result.stdout else "make"
        _pass(f"GNU Make  ({first_line})")
        return True
    except Exception as exc:
        _fail("GNU Make", str(exc))
        return False


def check_cppcheck() -> bool:
    binary = shutil.which("cppcheck")
    if binary is None:
        _fail("cppcheck", "Not found on PATH. Install with: sudo apt install cppcheck")
        return False
    try:
        result = subprocess.run(
            ["cppcheck", "--version"], capture_output=True, text=True, timeout=10
        )
        version = result.stdout.strip() or result.stderr.strip()
        _pass(f"cppcheck  ({version})")
        return True
    except Exception as exc:
        _fail("cppcheck", str(exc))
        return False


def check_uncrustify() -> bool:
    binary = shutil.which("uncrustify")
    if binary is None:
        _fail("uncrustify", "Not found on PATH. Install with: sudo apt install uncrustify")
        return False
    try:
        result = subprocess.run(
            ["uncrustify", "--version"], capture_output=True, text=True, timeout=10
        )
        version = result.stdout.strip() or result.stderr.strip()
        _pass(f"uncrustify  ({version})")
        return True
    except Exception as exc:
        _fail("uncrustify", str(exc))
        return False


def check_xc32(xc32_path: str, env_file: Path) -> bool:
    def _try_path(path: str) -> bool:
        binary = Path(path) / "xc32-gcc"
        if not binary.exists():
            return False
        try:
            result = subprocess.run(
                [str(binary), "--version"], capture_output=True, text=True, timeout=10
            )
            version_line = (result.stdout or result.stderr).splitlines()[0]
            _pass(f"XC32 Toolchain  ({version_line})")
            return True
        except Exception:
            return False

    if _try_path(xc32_path):
        return True

    _fail(
        "XC32 Toolchain",
        f"xc32-gcc not found at: {xc32_path}\n"
        "           Download from https://www.microchip.com/en-us/tools-resources/develop/mplab-xc-compilers",
    )
    new_path = prompt_path("XC32 Toolchain (bin/ directory)", "XC32_PATH")
    if new_path and _try_path(new_path):
        offer_save_to_env("XC32_PATH", new_path, env_file)
        return True
    return False


def check_dfp(dfp_path: str, env_file: Path) -> bool:
    def _try_path(path: str) -> bool:
        if Path(path).is_dir():
            _pass(f"Device Family Pack  ({path})")
            return True
        return False

    if _try_path(dfp_path):
        return True

    _fail(
        "Device Family Pack (DFP)",
        f"Directory not found: {dfp_path}\n"
        "           Install via MPLAB X → Tools → Packs,\n"
        "           or download from https://packs.download.microchip.com/",
    )
    new_path = prompt_path("Device Family Pack root directory", "DFP_PATH")
    if new_path and _try_path(new_path):
        offer_save_to_env("DFP_PATH", new_path, env_file)
        return True
    return False


def check_programmer(value: str) -> bool:
    valid = set(PROGRAMMER_VALUES.keys())
    if value in valid:
        full_name = PROGRAMMER_VALUES[value]
        _pass(f"Programmer  ({value} → {full_name})")
        return True
    opts = "  ".join(sorted(valid))
    _fail(
        "Programmer",
        f"Unknown value: {value!r}\n           Valid options: {opts}",
    )
    return False


def check_mplab_ide(mplab_ide: str | None, env_file: Path) -> bool:
    def _try_path(path: str) -> bool:
        if Path(path).is_file():
            _pass(f"MPLAB X IDE  ({path})")
            return True
        return False

    if mplab_ide and _try_path(mplab_ide):
        return True

    msg = (
        f"MPLAB X IDE not found: {mplab_ide}"
        if mplab_ide
        else "MPLAB_IDE environment variable is not set"
    )
    _warn(
        "MPLAB X IDE",
        f"{msg}\n"
        "           Required for mcc-refresh. Set MPLAB_IDE in .env.\n"
        "           Example: MPLAB_IDE=/opt/microchip/mplabx/v6.25/mplab_platform/bin/mplab_ide",
    )
    new_path = prompt_path("MPLAB X IDE binary", "MPLAB_IDE")
    if new_path and _try_path(new_path):
        offer_save_to_env("MPLAB_IDE", new_path, env_file)
        return True
    return not mplab_ide  # not configured = optional pass; configured-but-wrong = fail


def check_file_exists(key: str, path: str, env_file: Path, optional: bool = True) -> bool:
    if path and Path(path).is_file():
        _pass(f"{key}  ({path})")
        return True

    if not path:
        return optional

    _warn(
        key,
        f"File not found: {path}\n"
        f"           Set {key} in .env to point to an existing file.",
    )
    new_path = prompt_path(f"{key} file path", key)
    if new_path and Path(new_path).is_file():
        _pass(f"{key}  ({new_path})")
        offer_save_to_env(key, new_path, env_file)
        return True
    return False


def check_valid_string(key: str, value: str, allowed: list[str]) -> bool:
    if value in allowed:
        _pass(f"{key}  ({value})")
        return True
    opts = "  ".join(sorted(allowed))
    _fail(key, f"Unknown value: {value!r}\n           Valid options: {opts}")
    return False
