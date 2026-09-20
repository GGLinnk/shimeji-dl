from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArchiveCommandOptions:
    """Every `archive` command-line value, typed once at the parsing boundary.

    Carries only the output root, the blanket acceptance option, verbosity and quiet: the archive command performs no network work, so the download-only options have no place here.
    """

    targets: tuple[str, ...]
    output: Path
    verbose: bool
    quiet: bool
    yes: bool = False
