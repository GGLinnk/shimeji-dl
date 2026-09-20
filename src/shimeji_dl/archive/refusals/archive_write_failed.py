from __future__ import annotations

from pathlib import Path

from .refusal import ArchivingRefusal


class ArchiveWriteFailed(ArchivingRefusal):
    """Writing the archive itself failed after its `.part` file was already cleaned up."""

    def __init__(self, path: Path, cause: OSError) -> None:
        super().__init__(f"cannot write archive {path}: {cause}")
        self.path = path
        self.cause = cause
