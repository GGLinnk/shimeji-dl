from __future__ import annotations

from dataclasses import dataclass

from .target_kind import TargetKind


@dataclass(frozen=True, slots=True)
class LocalTarget:
    """A target reduced to its local shape and identifier, without any network access."""

    kind: TargetKind
    identifier: str
