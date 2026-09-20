from __future__ import annotations

from .refusal import ArchivingRefusal


class SourceNotFound(ArchivingRefusal):
    """A source's metadata is recorded locally, but none of it matches the requested site target."""

    def __init__(self, identifier: str) -> None:
        super().__init__(f"no such source here: {identifier!r}")
        self.identifier = identifier
