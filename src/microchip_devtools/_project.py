"""Project context helpers — read from environment vars set by Makefile.py."""

import os
from pathlib import Path


def project_name() -> str:
    """Return project name from env var or current directory name."""
    return os.environ.get("VOLTU_PROJECT_NAME", Path.cwd().name)


def project_root() -> Path:
    """Return project root from env var or current working directory."""
    return Path(os.environ.get("VOLTU_PROJECT_ROOT", str(Path.cwd())))
