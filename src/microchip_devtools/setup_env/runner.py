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
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from microchip_devtools.setup_env._ui import console
from microchip_devtools.setup_env.checks import (
    check_boot_hex,
    check_cppcheck,
    check_dfp,
    check_make,
    check_poetry,
    check_programmer,
    check_python,
    check_uncrustify,
    check_xc32,
)

_ENV_DESCRIPTIONS: dict[str, str] = {
    "XC32_PATH": "Path to Microchip XC32 toolchain bin/ directory",
    "DFP_PATH": "Path to the Device Family Pack (DFP) root directory",
    "IPE_CMD": "Path to the MPLAB IPE command-line script (ipecmd.sh)",
    "BOOT_HEX": "Path to the bootloader .hex file used by the flash-with-boot target",
    "PROGRAMMER": "Programmer/debugger tool short name (e.g. PK5, ICD4, SNAP)",
}


def _load_dotenv(env_file: Path) -> None:
    _dotenv_load(dotenv_path=env_file, override=False)


def _resolve(key: str, defaults: dict[str, str]) -> str:
    return os.path.expandvars(
        os.path.expanduser(os.environ.get(key, defaults.get(key, "")))
    )


def check(defaults: dict[str, str], env_file: Path) -> bool:
    console.print()
    console.rule("Checking prerequisites", style="bold blue")
    console.print()

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
    if "PROGRAMMER" in defaults:
        results.append(check_programmer(_resolve("PROGRAMMER", defaults)))

    passed = sum(results)
    total = len(results)
    console.print()

    if all(results):
        console.print(
            Panel(
                f"[green]✔ All {total} checks passed. The project is ready to build.[/green]\n"
                f"  Run [bold]make[/bold] or [bold]poetry run project-setup install[/bold] to continue.",
                border_style="green",
                padding=(0, 2),
            )
        )
    else:
        failed = total - passed
        console.print(
            Panel(
                f"[red]✗ {failed} of {total} checks failed.[/red]\n"
                f"  Fix the issues above, then run [bold]poetry run project-setup check[/bold] again.",
                border_style="red",
                padding=(0, 2),
            )
        )

    console.print()
    return all(results)


def install(
    defaults: dict[str, str], env_file: Path, skip_checks: bool = False
) -> None:
    if not skip_checks:
        ok = check(defaults, env_file)
        if not ok:
            console.print("[red]  Skipping install because checks failed.[/red]\n")
            sys.exit(1)

    console.print()
    console.rule("Installing Python environment", style="bold blue")
    console.print()
    try:
        import subprocess

        subprocess.run(["poetry", "env", "remove", "python"], check=False)
        subprocess.run(["poetry", "install", "--no-root"], check=True)
        console.print("\n[green]  Done. Python environment is ready.[/green]\n")
    except Exception as exc:
        console.print(f"\n[red]  `poetry install` failed: {exc}[/red]\n")
        sys.exit(1)


def env(defaults: dict[str, str]) -> None:
    console.print()
    console.rule("Environment variables", style="bold blue")
    console.print()

    table = Table(
        show_header=True,
        header_style="bold",
        padding=(0, 1),
        show_edge=False,
    )
    table.add_column("Variable", style="bold cyan", no_wrap=True)
    table.add_column("Current value")
    table.add_column("Default", style="dim")

    for key, default in defaults.items():
        current = os.environ.get(key)
        if current is None:
            value_display = f"[yellow](default) {default}[/yellow]"
        elif current == default:
            value_display = current
        else:
            value_display = f"[green]{current}[/green]  [yellow]← overridden[/yellow]"
        table.add_row(key, value_display, default)

    console.print(table)
    console.print()


def _prompt_env_form(defaults: dict[str, str], env_file: Path) -> None:
    console.print(
        Panel(
            "[bold yellow]ACTION REQUIRED — Configure your environment[/bold yellow]\n\n"
            "  Review each variable below.\n"
            "  Press [bold]Enter[/bold] to keep the default, or type a new value to override it.\n"
            "  Variables you override will be [bold green]uncommented[/bold green] in [cyan].env[/cyan].\n"
            "  Variables left at default stay commented out (no effect on the build).",
            border_style="yellow",
            padding=(1, 2),
            title="[bold yellow] .env setup [/bold yellow]",
        )
    )
    console.print()

    chosen: dict[str, str | None] = {}
    for key, default in defaults.items():
        desc = _ENV_DESCRIPTIONS.get(key, "")
        if desc:
            console.print(f"  [dim]{desc}[/dim]")
        value = Prompt.ask(
            f"  [bold cyan]{key}[/bold cyan]",
            default=default,
            console=console,
        )
        chosen[key] = value if value != default else None
        console.print()

    overridden = {k: v for k, v in chosen.items() if v is not None}

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
        if key in overridden:
            lines.append(f"{key}={overridden[key]}")
        else:
            lines.append(f"# {key}={default}")
        lines.append("")

    env_file.write_text("\n".join(lines))

    if overridden:
        keys_fmt = ", ".join(f"[cyan]{k}[/cyan]" for k in overridden)
        console.print(
            Panel(
                f"[green]✔ .env updated.[/green] Overridden: {keys_fmt}\n\n"
                f"  Run [bold]poetry run project-setup check[/bold] to verify your setup.",
                border_style="green",
                padding=(0, 2),
            )
        )
    else:
        console.print(
            Panel(
                "[green]✔ .env created.[/green] All variables left at their defaults (commented out).\n\n"
                "  Edit [cyan].env[/cyan] manually any time to override a value.\n"
                "  Run [bold]poetry run project-setup check[/bold] to verify your setup.",
                border_style="green",
                padding=(0, 2),
            )
        )
    console.print()


def init_env(defaults: dict[str, str], env_file: Path, force: bool = False) -> None:
    env_example = env_file.parent / ".env.example"

    if env_file.exists() and not force:
        console.print(
            "[yellow]  .env already exists. Use --force to overwrite it.[/yellow]\n"
        )
        return

    if env_example.exists():
        import shutil

        shutil.copy(env_example, env_file)
        console.print(f"[green]  Created .env from {env_example.name}.[/green]")
        _prompt_env_form(defaults, env_file)
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
    console.print(
        f"[green]  Created .env with {len(defaults)} commented-out variables.[/green]"
    )
    _prompt_env_form(defaults, env_file)


def main(defaults: dict[str, str] | None = None) -> None:
    """Entry point. Projects pass merged COMMON_DEFAULTS | PROJECT_DEFAULTS."""
    if defaults is None:
        import sys

        from microchip_devtools.setup_env.defaults import COMMON_DEFAULTS

        cwd = str(Path.cwd())
        if cwd not in sys.path:
            sys.path.insert(0, cwd)

        try:
            from pymake import PROJECT_DEFAULTS  # type: ignore

            defaults = COMMON_DEFAULTS | PROJECT_DEFAULTS
        except ImportError:
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

    assert defaults is not None

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
