from __future__ import annotations

from pathlib import Path

from .refusal import ArchivingRefusal


class EmptyOutputRoot(ArchivingRefusal):
    """No character was found anywhere under the output root."""

    def __init__(self, output_root: Path) -> None:
        super().__init__(f"nothing to archive: no character was found under {output_root}")
        self.output_root = output_root
