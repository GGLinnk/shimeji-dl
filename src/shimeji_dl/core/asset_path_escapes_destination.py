from __future__ import annotations

from pathlib import Path


class AssetPathEscapesDestination(OSError):
    """Raised when a resolved asset path falls outside its destination directory."""

    def __init__(self, dest: Path, path: str) -> None:
        super().__init__(f"asset path {path!r} escapes destination {dest}")
        self.dest = dest
        self.path = path
