"""Transparent passthrough wrapper for the pinned uncrustify binary.

Unlike the opinionated ``format`` command (see :mod:`uncrustify`), this exposes
the pinned, checksum-verified uncrustify binary directly: every CLI argument is
forwarded verbatim and stdio is inherited, so the command behaves exactly like
invoking the real binary -- but always at the project-pinned version.
"""

from __future__ import annotations

import subprocess
import sys

from microchip_devtools.format.uncrustify_bin import resolve_uncrustify


def main() -> None:
    try:
        binary = resolve_uncrustify()
    except Exception as exc:  # resolution / download / checksum failure
        print(f"uncrustify: {exc}", file=sys.stderr)
        sys.exit(1)

    # No capture -> child inherits parent fd 0/1/2 (full passthrough stdio).
    # No check -> the binary's exit code flows straight through.
    result = subprocess.run([str(binary), *sys.argv[1:]])
    sys.exit(result.returncode)
