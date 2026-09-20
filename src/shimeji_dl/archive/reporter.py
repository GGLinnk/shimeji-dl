from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ArchiveReporter(Protocol):
    """Progress, outcome and per-item warning surface for the archiver and its resolver."""

    def archive_started(self, name: str, entry_count: int, byte_total: int) -> None: ...

    def archive_entry_written(self, entries_done: int, entry_count: int) -> None: ...

    def archive_finished(self, path: Path, entry_count: int, size: int) -> None: ...

    def warning(self, message: str) -> None: ...
