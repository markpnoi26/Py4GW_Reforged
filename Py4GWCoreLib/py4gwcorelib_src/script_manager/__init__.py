"""Script manager — flat, metadata-driven discovery for ``Scripts/``."""

from .discovery import RESOURCES
from .discovery import SUBSUMES
from .discovery import ScriptMeta
from .discovery import ScriptRegistry
from .discovery import build_meta
from .discovery import find_block
from .discovery import parse_metadata

__all__ = [
    "RESOURCES",
    "SUBSUMES",
    "ScriptMeta",
    "ScriptRegistry",
    "build_meta",
    "find_block",
    "parse_metadata",
]
