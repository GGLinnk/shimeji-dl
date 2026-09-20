from __future__ import annotations

from .refusal import ArchivingRefusal


class ArchiveNameInvalid(ArchivingRefusal):
    """A derived archive name failed filename validation."""

    def __init__(self, name: str) -> None:
        super().__init__(f"derived archive name is not a valid filename: {name!r}")
        self.name = name
