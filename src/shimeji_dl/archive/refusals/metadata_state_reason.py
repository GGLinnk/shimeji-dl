from __future__ import annotations

from ..metadata_state import MetadataState

# The one owner of each causal metadata state's explanation text.
_REASON = {
    MetadataState.UNREADABLE: (
        "a local metadata document could not be read or parsed; the cause is local, "
        "not a remote manifest problem, archive characters individually or repair the document"
    ),
    MetadataState.NO_MANIFEST: "no downloaded character had a source manifest available, archive characters individually",
    MetadataState.MANIFEST_WITHOUT_GROUP: (
        "every downloaded character's source manifest records no collection, archive characters individually"
    ),
    MetadataState.NO_DOCUMENT: (
        "no downloaded character carries a metadata document; metadata writing was disabled, "
        "archive characters individually or re-download with metadata enabled"
    ),
}


def reason_for(state: MetadataState) -> str:
    """The one shared causal-explanation text for a metadata state."""
    return _REASON[state]
