"""Declarative registry of project-specific (foreign) environment variables."""

from dataclasses import dataclass, field
from enum import Enum


class CheckType(Enum):
    FILE_EXISTS = "file_exists"
    DIR_EXISTS = "dir_exists"
    VALID_STRING = "valid_string"


@dataclass
class ForeignVarDef:
    key: str
    description: str
    check_type: CheckType
    optional: bool = True
    allowed_values: list[str] = field(default_factory=list)


FOREIGN_VAR_REGISTRY: list[ForeignVarDef] = [
    ForeignVarDef(
        key="BOOT_ELF",
        description="Path to the bootloader .elf file used by the flash-with-boot target",
        check_type=CheckType.FILE_EXISTS,
        optional=False,
    ),
]
