from rich.console import Console
from rich.table import Table
from rich.theme import Theme

_THEME = Theme(
    {
        "cmd": "bold cyan",
        "desc": "default",
    }
)

COMMANDS = [
    ("list", "List all available commands"),
    ("setup", "Check prerequisites and install project deps"),
    ("validate-fmt3", "Detect XC32 fmt=3 compiler bug in ELF/object files"),
    ("merge-hex", "Merge bootloader + app HEX into a single image"),
    ("format", "Format C/H source files with uncrustify"),
    ("mcc-refresh", "Force full MCC regeneration workflow"),
    ("check-peripheral", "Validate MCC-generated peripheral config files"),
    ("check-clock", "Validate clock/oscillator configuration (MCC + #pragma config)"),
    ("parse-hardware", "Show hardware config parsed from Harmony YML files"),
    ("sync-mplab", "Sync MPLAB X project files"),
    ("check-clangd", "Check Clangd configuration and diagnostics"),
]


def main():
    console = Console(theme=_THEME, highlight=False)
    table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
    table.add_column(style="cmd", no_wrap=True)
    table.add_column(style="desc")
    for cmd, desc in COMMANDS:
        table.add_row(cmd, desc)
    console.print(table)
