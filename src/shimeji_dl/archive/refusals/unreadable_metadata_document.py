from __future__ import annotations

from ..metadata_state import MetadataState
from .metadata_state_reason import reason_for
from .refusal import ArchivingRefusal


class UnreadableMetadataDocument(ArchivingRefusal):
    """A local metadata document exists but could not be read or decoded.

    Distinct from a document that decoded cleanly and simply carries no group: this cause is local and unrelated to the remote manifest.
    """

    def __init__(self, identifier: str, *, subject: str) -> None:
        super().__init__(f"cannot resolve {subject} {identifier!r}: {reason_for(MetadataState.UNREADABLE)}")
        self.identifier = identifier
        self.subject = subject
