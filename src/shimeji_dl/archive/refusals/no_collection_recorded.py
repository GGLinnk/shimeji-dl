from __future__ import annotations

from typing import Literal

from ..metadata_state import MetadataState
from .metadata_state_reason import reason_for
from .refusal import ArchivingRefusal


class NoCollectionRecorded(ArchivingRefusal):
    """Metadata documents exist, but none of them ever records a source collection."""

    def __init__(
        self,
        identifier: str,
        state: Literal[MetadataState.NO_MANIFEST, MetadataState.MANIFEST_WITHOUT_GROUP],
    ) -> None:
        super().__init__(
            f"cannot resolve collection {identifier!r}: no downloaded character records a "
            f"source collection; {reason_for(state)}"
        )
        self.identifier = identifier
        self.state = state
