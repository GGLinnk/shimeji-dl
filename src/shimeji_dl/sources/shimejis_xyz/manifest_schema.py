from __future__ import annotations

from typing import Annotated

import msgspec

# Generous headroom over the largest observed shimejis.xyz action or
# behavior XML document (tens of kilobytes for a full pose set).
MAX_CONFIG_XML_LENGTH = 2_000_000
# Conventional safe upper bound for an HTTP(S) URL.
MAX_URL_LENGTH = 2048
# Generous headroom over the longest observed metadata string (a
# third-party download URL, under 100 characters).
MAX_METADATA_STRING_LENGTH = 500

BoundedConfigXml = Annotated[str, msgspec.Meta(max_length=MAX_CONFIG_XML_LENGTH)]
BoundedUrl = Annotated[str, msgspec.Meta(max_length=MAX_URL_LENGTH)]
BoundedMetadataString = Annotated[str, msgspec.Meta(max_length=MAX_METADATA_STRING_LENGTH)]


def _null_raw() -> msgspec.Raw:
    return msgspec.Raw(b"null")


class ManifestEnvelope(msgspec.Struct):
    """Top-level shimejis.xyz configuration payload, decoded field by field.

    Each field stays as raw, undecoded JSON (defaulting to a JSON null when
    absent) so one malformed field never invalidates its siblings.
    """

    actions: msgspec.Raw = msgspec.field(default_factory=_null_raw)
    behaviors: msgspec.Raw = msgspec.field(default_factory=_null_raw)
    info: msgspec.Raw = msgspec.field(default_factory=_null_raw)
    sprites: msgspec.Raw = msgspec.field(default_factory=_null_raw)
    spritesheet: msgspec.Raw = msgspec.field(default_factory=_null_raw)
    metadata: msgspec.Raw = msgspec.field(default_factory=_null_raw)


class SpriteRegionWire(msgspec.Struct, forbid_unknown_fields=True):
    """A single sprite atlas region, coordinates in source pixels."""

    x: Annotated[int, msgspec.Meta(ge=0)]
    y: Annotated[int, msgspec.Meta(ge=0)]
    width: Annotated[int, msgspec.Meta(gt=0)]
    height: Annotated[int, msgspec.Meta(gt=0)]


class ManifestMetadataWire(msgspec.Struct):
    """The shimejis.xyz metadata block, typed and bounded but open-ended.

    Field names match the wire's own camelCase keys verbatim, so decoding
    back to a plain dict for metadata.json changes no persisted key name.
    An unknown key is ignored rather than voiding the whole block, since
    every known field still survives; unlike a sprite entry, there is no
    single malformed item here to drop instead.
    """

    group: BoundedMetadataString | None = None
    groupName: BoundedMetadataString | None = None
    shimeji: BoundedMetadataString | None = None
    shimejiName: BoundedMetadataString | None = None
    sourceUrl: BoundedMetadataString | None = None
    artistName: BoundedMetadataString | None = None
    iconUrl: BoundedMetadataString | None = None
    thumbnailUrl: BoundedMetadataString | None = None
