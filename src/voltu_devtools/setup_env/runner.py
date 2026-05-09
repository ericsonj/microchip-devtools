"""
setup_env runner — Environment checker and project installer.

Called by each project's thin pymake/setup_env.py wrapper, which passes
the merged DEFAULTS (COMMON_DEFAULTS | PROJECT_DEFAULTS).

Usage (via project wrapper):
    poetry run setup_env [action]

Actions:
    check      Verify all prerequisites (default)
    install    Run `poetry install` to set up the Python environment
    env        Show current ENV variable values vs. their defaults
    init-env   Create a .env file from defaults
    all        Run check → install in sequence

Exit codes:
    0  All checks passed / action completed successfully
    1  One or more checks failed
"""

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv as _dotenv_load

from voltu_devtools.setup_env._ui import _bold, _green, _red, _yellow
from voltu_devtools.setup_env.checks import (
    check_boot_hex,
    check_cppcheck,
    check_dfp,
    check_make,
    check_poetry,
    check_python,
    check_uncrustify,
    check_xc32,
)

_ENV_DESCRIPTIONS: dict[str, str] = {
    "XC32_PATH": "Path to Microchip XC32 toolchain bin/ directory",
    "DFP_PATH":  "Path to the Device Family Pack (DFP) root directory",
    "IPE_CMD":   "Path to the MPLAB IPE command-line script (ipecmd.sh)",
    "BOOT_HEX":  "Path to the bootloader .hex file used by the flash-with-boot target",
}


def _load_dotenv(env_file: Path) -> None:
    _dotenv_load(dotenv_path=env_file, override=False)


def _resolve(key: str, defaults: dict[str, str]) -> str:
    return os.path.expandvars(os.path.expanduser(os.environ.get(key, defaults.get(key, ""))))


def check(defaults: dict[str, str], env_file: Path) -> bool:
    print(_bold("\n── Checking prerequisites ──────────────────────────────\n"))

    results: list[bool] = [
        check_python(),
        check_poetry(),
        check_make(),
        check_cppcheck(),
        check_uncrustify(),
    ]

    if "XC32_PATH" in defaults:
        results.append(check_xc32(_resolve("XC32_PATH", defaults), env_file))
    if "DFP_PATH" in defaults:
        results.append(check_dfp(_resolve("DFP_PATH", defaults), env_file))
    if "BOOT_HEX" in defaults:
        results.append(check_boot_hex(_resolve("BOOT_HEX", defaults), env_file))

    passed = sum(results)
    total = len(results)
    print()
    if all(results):
        print(_green(f"  All {total} checks passed. The project is ready to build."))
        print(f"  Run {_bold('make')} or {_bold('poetry run setup_env install')} to continue.\n")
    else:
        failed = total - passed
        print(_red(f"  {failed} of {total} checks failed."))
        print(f"  Fix the issues above, then run {_bold('poetry run setup_env check')} again.\n")

    return all(results)


def install(defaults: dict[str, str], env_file: Path, skip_checks: bool = False) -> None:
    if not skip_checks:
        ok = check(defaults, env_file)
        if not ok:
            print(_red("  Skipping install because checks failed.\n"))
            sys.exit(1)

    print(_bold("\n── Installing Python environment ────────────────────────\n"))
    try:
        import subprocess
        subprocess.run(["poetry", "install", "--no-root"], check=True)
        print(_green("\n  Done. Python environment is ready.\n"))
    except Exception as exc:
        print(_red(f"\n  `poetry install` failed: {exc}\n"))
        sys.exit(1)


def env(defaults: dict[str, str]) -> None:
    print(_bold("\n── Environment variables ────────────────────────────────\n"))
    col_w = max(len(k) for k in defaults) + 2 if defaults else 12
    print(f"  {'Variable':<{col_w}}  {'Current value':<50}  Default")
    print(f"  {'-' * col_w}  {'-' * 50}  {'-' * 50}")
    for key, default in defaults.items():
        current = os.environ.get(key)
        if current is None:
            display = _yellow(f"(default) {default}")
        elif current == default:
            display = current
        else:
            display = _green(current) + _yellow("  ← overridden")
        print(f"  {key:<{col_w}}  {display}")
    print()


def init_env(defaults: dict[str, str], env_file: Path, force: bool = False) -> None:
    env_example = env_file.parent / ".env.example"

    if env_file.exists() and not force:
        print(_yellow(f"  .env already exists. Use --force to overwrite it.\n"))
        return

    if env_example.exists():
        import shutil
        shutil.copy(env_example, env_file)
        print(_green(f"  Created .env from {env_example.name}."))
        print(f"  Open .env and uncomment the variables you want to override.\n")
        return

    lines = [
        "# .env — local overrides for environment variables",
        "# Shell-level exports always take priority over values set here.",
        "# Uncomment and edit only the variables you need to override.",
        "",
    ]
    for key, default in defaults.items():
        desc = _ENV_DESCRIPTIONS.get(key, "")
        if desc:
            lines.append(f"# {desc}")
        lines.append(f"# {key}={default}")
        lines.append("")

    env_file.write_text("\n".join(lines))
    print(_green(f"  Created .env with {len(defaults)} commented-out variables."))
    print(f"  Open .env and uncomment the variables you want to override.\n")


def main(defaults: dict[str, str] | None = None) -> None:
    """Entry point. Projects pass merged COMMON_DEFAULTS | PROJECT_DEFAULTS."""
    if defaults is None:
        from voltu_devtools.setup_env.defaults import COMMON_DEFAULTS
        defaults = COMMON_DEFAULTS

    env_file = Path(".env")
    _load_dotenv(env_file)

    parser = argparse.ArgumentParser(
        prog="setup_env",
        description="Verify and install everything needed to compile the firmware.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
actions:
  check     Verify all prerequisites (default)
  install   Run poetry install
  env       Show ENV variable values vs. defaults
  init-env  Create a .env file from defaults
  all       check → install in sequence
        """,
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="check",
        choices=["check", "install", "env", "init-env", "all"],
    )
    parser.add_argument("--skip-checks", action="store_true")
    parser.add_argument("--force", action="store_true")

    args = parser.parse_args()

    if args.action == "check":
        ok = check(defaults, env_file)
        sys.exit(0 if ok else 1)
    elif args.action == "install":
        install(defaults, env_file, skip_checks=args.skip_checks)
    elif args.action == "env":
        env(defaults)
    elif args.action == "init-env":
        init_env(defaults, env_file, force=args.force)
    elif args.action == "all":
        ok = check(defaults, env_file)
        if not ok:
            sys.exit(1)
        install(defaults, env_file, skip_checks=True)
