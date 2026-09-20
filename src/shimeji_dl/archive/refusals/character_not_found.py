from __future__ import annotations

from .refusal import ArchivingRefusal


class CharacterNotFound(ArchivingRefusal):
    """A character target names no local directory, regardless of any other character's metadata state."""

    def __init__(self, identifier: str) -> None:
        super().__init__(f"no such character here: {identifier!r}")
        self.identifier = identifier
