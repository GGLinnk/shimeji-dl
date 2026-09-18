from __future__ import annotations

import re
from collections.abc import Iterable

_NUMERIC_SPRITE_RE = re.compile(r"^shime([1-9][0-9]*)\.png$", re.IGNORECASE)


def numeric_sprite_index(path: str) -> int | None:
    """Return N for a root-level ``shimeN.png`` sprite.

    Nested/custom filenames remain XML-only discoveries. Numeric probing is
    intentionally limited to the conventional root-level Shimeji namespace.
    """
    normalized = path.replace("\\", "/").lstrip("/")
    if "/" in normalized:
        return None
    match = _NUMERIC_SPRITE_RE.fullmatch(normalized)
    return int(match.group(1)) if match else None


def numeric_sprite_indices(paths: Iterable[str]) -> set[int]:
    return {index for path in paths if (index := numeric_sprite_index(path)) is not None}


def quiescence_span(hits: Iterable[int], mode: str, *, span_hint: int = 0) -> int:
    """Derive a tail-search distance from the pack shape instead of an index cap.

    A dense normal pack quickly settles at a small tail. Sparse packs naturally
    expand the search because their observed gaps are larger. ``deep`` increases
    confidence by using a wider evidence-derived quiet region.
    """
    ordered = sorted(set(hits))
    largest_gap = max((right - left - 1 for left, right in zip(ordered, ordered[1:])), default=0)
    highest = ordered[-1] if ordered else 0
    bit_scale = max(1, highest.bit_length())

    if mode == "deep":
        base = 128
        gap_factor = 8
        position_factor = 8
        hint_factor = 2
    else:
        base = 32
        gap_factor = 4
        position_factor = 4
        hint_factor = 1

    return max(
        base,
        (largest_gap + 1) * gap_factor,
        bit_scale * position_factor,
        span_hint * hint_factor,
    )
