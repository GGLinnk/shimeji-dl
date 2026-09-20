from __future__ import annotations

from .refusal import ArchivingRefusal


class CollectionNotFound(ArchivingRefusal):
    """Collection metadata is recorded locally, but none of it matches the requested target."""

    def __init__(self, identifier: str) -> None:
        super().__init__(f"no such collection here: {identifier!r}")
        self.identifier = identifier
