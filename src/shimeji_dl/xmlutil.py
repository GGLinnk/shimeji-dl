from __future__ import annotations

import xml.etree.ElementTree as ET

from .models import ImageRef
from .utils import normalize_asset_ref


def is_valid_xml(data: bytes) -> bool:
    try:
        ET.fromstring(data)
    except (ET.ParseError, ValueError):
        return False
    return True


def extract_image_refs(data: bytes) -> list[ImageRef]:
    """Extract image file references from any XML attribute.

    Shimeji actions normally use ``Pose Image=\"/shime1.png\"``. Looking at
    every attribute whose value resolves to an image path also covers custom
    schemas without accidentally treating ``ImageAnchor`` as a filename.
    """
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError):
        return []

    refs: list[ImageRef] = []
    seen: set[tuple[str, str | None]] = set()
    for element in root.iter():
        for value in element.attrib.values():
            normalized = normalize_asset_ref(value)
            if normalized is None:
                continue
            path, absolute_url = normalized
            key = (path, absolute_url)
            if key in seen:
                continue
            seen.add(key)
            refs.append(ImageRef(value=value, path=path, absolute_url=absolute_url))
    return refs
