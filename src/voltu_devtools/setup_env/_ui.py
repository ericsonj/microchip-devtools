"""Terminal output helpers for setup_env — color, pass/fail/warn, interactive prompts."""

import sys
from pathlib import Path

_USE_COLOR = sys.stdout.isatty()


def _green(text: str) -> str:
    return f"\033[32m{text}\033[0m" if _USE_COLOR else text


def _red(text: str) -> str:
    return f"\033[31m{text}\033[0m" if _USE_COLOR else text


def _yellow(text: str) -> str:
    return f"\033[33m{text}\033[0m" if _USE_COLOR else text


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m" if _USE_COLOR else text


def _pass(label: str) -> None:
    print(f"  {_green('✔ PASS')}  {label}")


def _fail(label: str, reason: str) -> None:
    print(f"  {_red('✗ FAIL')}  {label}")
    print(f"           {_yellow('→')} {reason}")


def _warn(label: str, reason: str) -> None:
    print(f"  {_yellow('⚠ WARN')}  {label}")
    print(f"           {_yellow('→')} {reason}")


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def prompt_path(label: str, env_key: str) -> str | None:
    if not _is_interactive():
        return None
    print()
    print(f"  {_yellow('?')} {label} was not found at the expected location.")
    print(f"    You can set {_bold(env_key)} in your shell or in the .env file.")
    try:
        answer = input(f"    Enter the correct path (or press Enter to skip): ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return None
    return answer if answer else None


def offer_save_to_env(key: str, value: str, env_file: Path) -> None:
    if not _is_interactive():
        return
    try:
        answer = input(f"    Save {key}={value} to .env for future runs? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return
    if answer in ("y", "yes"):
        with env_file.open("a") as f:
            f.write(f"\n{key}={value}\n")
        print(f"    {_green('Saved.')} You can edit .env at any time to update it.")
