from __future__ import annotations

from pathlib import Path

from .refusal import ArchivingRefusal


class ArchiveOverwriteRefused(ArchivingRefusal):
    """The archive's final file already exists and replacing it was refused, or could not be asked."""

    def __init__(self, path: Path, *, no_terminal: bool = False) -> None:
        reason = "no confirmation could be asked: no interactive terminal" if no_terminal else "not confirmed"
        super().__init__(f"archive already exists, {reason}: {path}")
        self.path = path
        self.no_terminal = no_terminal
