from __future__ import annotations

import msgspec


class CollectionIdentity(msgspec.Struct):
    """The collection identity fields read back from a character's metadata document.

    Field names match `ManifestMetadataWire`'s own `group`/`groupName` verbatim.
    Both fields read as absent for `{"available": false}` (no manifest) and for `{"available": true, "metadata": {}}` (a manifest recording no collection); `SourceManifestRecord.available` is what tells those two apart.
    """

    group: str | None = None
    groupName: str | None = None


class SourceManifestRecord(msgspec.Struct):
    available: bool = False
    metadata: CollectionIdentity | None = None


class DiscoveryRecord(msgspec.Struct):
    source_manifest: SourceManifestRecord | None = None


class CharacterMetadataRecord(msgspec.Struct):
    """The subset of a character's `metadata.json` the local resolver reads.

    Unknown fields are ignored by default, so an addition to the written document never breaks this read.
    """

    source_adapter: str | None = None
    discovery: DiscoveryRecord | None = None
