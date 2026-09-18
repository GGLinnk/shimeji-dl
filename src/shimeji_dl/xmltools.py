from __future__ import annotations

import re
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree as DET

from .utils import sanitize_asset_path

_IMAGE_RE = re.compile(r"\bImage\s*=\s*(['\"])(.*?)\1", re.IGNORECASE | re.DOTALL)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def is_probable_config(data: bytes, kind: str) -> bool:
    if not data or b"<" not in data:
        return False
    try:
        root = DET.fromstring(data)
    except (ParseError, ValueError):
        return False

    names = {_local_name(node.tag).lower() for node in root.iter() if isinstance(node.tag, str)}
    if kind == "actions":
        return "action" in names or "actionlist" in names
    if kind == "behaviors":
        return "behavior" in names or "behaviorlist" in names
    return True


def image_references(data: bytes) -> list[str]:
    """Return safe unique image paths referenced by an actions XML.

    A regex fallback is used only if the XML cannot be parsed. This is useful for
    old community files with slightly malformed XML declarations.
    """
    values: list[str] = []

    try:
        root = DET.fromstring(data)
        for node in root.iter():
            for key, value in node.attrib.items():
                if _local_name(key).lower() == "image":
                    values.append(value)
    except (ParseError, ValueError):
        text = data.decode("utf-8", errors="replace")
        values.extend(match.group(2) for match in _IMAGE_RE.finditer(text))

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            clean = sanitize_asset_path(value)
        except ValueError:
            continue
        key = clean.casefold()
        if key not in seen:
            seen.add(key)
            result.append(clean)
    return result
