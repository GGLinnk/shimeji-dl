from __future__ import annotations

from pathlib import Path

from .refusal import ArchivingRefusal


class ArchiveSourceUnreadable(ArchivingRefusal):
    """The image root, a character directory's recursive listing, one of its entries, or the finished archive could not be listed or stat'ed."""

    def __init__(self, path: Path, cause: OSError) -> None:
        super().__init__(f"cannot read {path}: {cause}")
        self.path = path
        self.cause = cause
