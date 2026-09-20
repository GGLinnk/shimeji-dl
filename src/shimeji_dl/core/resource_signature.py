from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ResourceSignature:
    """One resource kind's magic-byte matcher, keyed by file extension in its table."""

    kind: Literal["image", "audio"]
    matches: Callable[[bytes], bool]
