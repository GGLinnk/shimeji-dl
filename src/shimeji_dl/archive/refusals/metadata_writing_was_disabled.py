from __future__ import annotations

from ..metadata_state import MetadataState
from .metadata_state_reason import reason_for
from .refusal import ArchivingRefusal


class MetadataWritingWasDisabled(ArchivingRefusal):
    """No downloaded character carries a metadata document at all."""

    def __init__(self, identifier: str, *, subject: str) -> None:
        super().__init__(f"cannot resolve {subject} {identifier!r}: {reason_for(MetadataState.NO_DOCUMENT)}")
        self.identifier = identifier
        self.subject = subject
