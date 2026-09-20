from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..target.local_target import LocalTarget
from ..target.target_kind import TargetKind

SOURCE_KEY = "shimejis.xyz"
SITE = f"https://{SOURCE_KEY}"
DIRECTORY = f"{SITE}/directory"
CHARACTER_PREFIX = "/directory/shimeji/"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
WHOLE_SITE_TARGETS = frozenset({SOURCE_KEY, f"www.{SOURCE_KEY}"})
PACK_SUFFIX = "-shimeji-pack"


def pack_slug(identifier: str) -> str:
    """The collection archive name the site publishes for a group identifier: the identifier with the pack suffix."""
    return f"{identifier}{PACK_SUFFIX}"


def reduce(target: str) -> LocalTarget | None:
    """Classify a target's local shape and identifier, purely from its text.

    Mirrors the shape rules `ShimejisXYZSource.suitable`/`extract` apply for building a network request, without building one: the network side keeps its own URL construction on the raw target, this only names the shape.
    A bare identifier always names a character, folded to lowercase exactly as the network side folds it: a mixed-case bare string is still a character candidate by its lowered form.
    Returns `None` when the target does not belong to this source at all.
    """
    normalized = target.strip()
    lowered = normalized.lower().rstrip("/")
    if lowered in WHOLE_SITE_TARGETS:
        return LocalTarget(TargetKind.SITE, SOURCE_KEY)

    if "://" not in normalized:
        if lowered.endswith(PACK_SUFFIX):
            return LocalTarget(TargetKind.COLLECTION, lowered[: -len(PACK_SUFFIX)])
        if SLUG_RE.fullmatch(lowered):
            return LocalTarget(TargetKind.CHARACTER, lowered)
        return None

    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
    except ValueError:
        # A malformed URL (an unbalanced IPv6 literal, for instance) belongs to no source.
        return None
    if parsed.scheme not in {"http", "https"} or hostname not in WHOLE_SITE_TARGETS:
        return None
    path = parsed.path.rstrip("/")
    if path in {"", "/directory"}:
        return LocalTarget(TargetKind.SITE, SOURCE_KEY)
    if path.startswith(CHARACTER_PREFIX):
        slug = path[len(CHARACTER_PREFIX):]
        return LocalTarget(TargetKind.CHARACTER, slug) if SLUG_RE.fullmatch(slug) else None
    if path.startswith("/directory/") and path.count("/") == 2:
        name = path[len("/directory/"):]
        if name.endswith(PACK_SUFFIX):
            name = name[: -len(PACK_SUFFIX)]
        return LocalTarget(TargetKind.COLLECTION, name)
    return None
