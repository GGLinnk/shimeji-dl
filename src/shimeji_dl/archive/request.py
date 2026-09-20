from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ArchiveRequest:
    """What to archive and under what name: the input to the shared archiver.

    `characters` are the character directories to include; the archiver always roots every entry at the parent of `img/`, so `img/` itself is the archive's single top-level entry regardless of how many directories are listed here.
    """

    name: str
    characters: tuple[Path, ...]
