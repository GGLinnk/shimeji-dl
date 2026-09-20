from __future__ import annotations

from .refusal import ArchivingRefusal


class UnsupportedTarget(ArchivingRefusal):
    """A target string is shaped as a URL, but no registered source's local vocabulary accepts it."""

    def __init__(self, target: str) -> None:
        super().__init__(f"no source supports: {target}")
        self.target = target
