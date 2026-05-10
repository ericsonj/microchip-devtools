"""Terminal output helpers for setup_env — rich-powered."""

import sys
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt

console = Console(highlight=False)


def _pass(label: str) -> None:
    console.print(f"  [green]✔ PASS[/green]  {label}")


def _fail(label: str, reason: str) -> None:
    console.print(f"  [red]✗ FAIL[/red]  {label}")
    console.print(f"           [yellow]→[/yellow] {reason}")


def _warn(label: str, reason: str) -> None:
    console.print(f"  [yellow]⚠ WARN[/yellow]  {label}")
    console.print(f"           [yellow]→[/yellow] {reason}")


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def prompt_path(label: str, env_key: str) -> str | None:
    if not _is_interactive():
        return None
    console.print()
    console.print(f"  [yellow]?[/yellow] [bold]{label}[/bold] was not found at the expected location.")
    console.print(f"    You can set [bold]{env_key}[/bold] in your shell or .env file.")
    try:
        answer = Prompt.ask(
            "    Enter the correct path (or press Enter to skip)",
            default="",
            console=console,
        ).strip()
    except (EOFError, KeyboardInterrupt):
        console.print()
        return None
    return answer if answer else None


def offer_save_to_env(key: str, value: str, env_file: Path) -> None:
    if not _is_interactive():
        return
    try:
        save = Confirm.ask(
            f"    Save {key}={value} to .env for future runs?",
            default=False,
            console=console,
        )
    except (EOFError, KeyboardInterrupt):
        console.print()
        return
    if save:
        with env_file.open("a") as f:
            f.write(f"\n{key}={value}\n")
        console.print("    [green]Saved.[/green] You can edit .env at any time to update it.")
