from __future__ import annotations

from enum import Enum


class MetadataState(Enum):
    """The collection-side local metadata state paired with a target miss, distinct from the miss itself."""

    UNREADABLE = "unreadable"
    NO_MANIFEST = "no_manifest"
    MANIFEST_WITHOUT_GROUP = "manifest_without_group"
    NO_DOCUMENT = "no_document"
