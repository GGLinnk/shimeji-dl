from __future__ import annotations

from enum import Enum


class TargetKind(Enum):
    """What scope a target designates once reduced, independent of any source."""

    SITE = "site"
    COLLECTION = "collection"
    CHARACTER = "character"
