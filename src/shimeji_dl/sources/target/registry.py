from __future__ import annotations

from ...core.interfaces import SourceAdapter
from ..shimejis_xyz.adapter import ShimejisXYZSource


def default_sources() -> dict[str, SourceAdapter]:
    source: SourceAdapter = ShimejisXYZSource()
    return {source.key: source}


__all__ = ["default_sources"]
