from __future__ import annotations

from .refusal import ArchivingRefusal


class NoSourceRecorded(ArchivingRefusal):
    """Metadata documents exist, but none of them ever records a source adapter.

    `source_adapter` is written unconditionally on every metadata document, whether or not a source manifest was ever available, so its absence has exactly one cause, unlike the collection axis: a metadata document that predates this field, or one hand-edited to drop it.
    """

    def __init__(self, identifier: str) -> None:
        super().__init__(
            f"cannot resolve source {identifier!r}: a metadata document is present but records no source adapter"
        )
        self.identifier = identifier
