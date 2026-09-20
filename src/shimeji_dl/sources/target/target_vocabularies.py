from __future__ import annotations

from collections.abc import Callable

from ..shimejis_xyz.target_vocabulary import SOURCE_KEY
from ..shimejis_xyz.target_vocabulary import reduce as reduce_shimejis_xyz
from .local_target import LocalTarget

# Every registered source's network-free target vocabulary, keyed by source key.
# This module imports nothing beyond the vocabulary modules themselves, so classifying a target pulls in no adapter's network dependency.
TARGET_VOCABULARIES: dict[str, Callable[[str], LocalTarget | None]] = {
    SOURCE_KEY: reduce_shimejis_xyz,
}


def reduce_target(target: str) -> LocalTarget | None:
    """Classify a target against every registered vocabulary, first match wins."""
    for reduce in TARGET_VOCABULARIES.values():
        local = reduce(target)
        if local is not None:
            return local
    return None


__all__ = ["TARGET_VOCABULARIES", "reduce_target"]
