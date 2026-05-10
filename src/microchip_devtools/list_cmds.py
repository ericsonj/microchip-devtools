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
    ("mchp-list", "List all available mchp commands"),
    ("mchp-setup", "Check prerequisites and install project deps"),
    ("mchp-xc32", "Detect XC32 fmt=3 compiler bug in ELF/object files"),
    ("mchp-hex", "Merge bootloader + app HEX into a single image"),
    ("mchp-fmt", "Format C/H source files with uncrustify"),
    ("mchp-mcc", "Force full MCC regeneration workflow"),
    ("mchp-periph", "Validate MCC-generated peripheral config files"),
    ("mchp-hw", "Show hardware config parsed from Harmony YML files"),
]


def main():
    console = Console(theme=_THEME, highlight=False)
    table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
    table.add_column(style="cmd", no_wrap=True)
    table.add_column(style="desc")
    for cmd, desc in COMMANDS:
        table.add_row(cmd, desc)
    console.print(table)
