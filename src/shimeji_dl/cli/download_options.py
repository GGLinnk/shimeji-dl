from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .probe_mode import ProbeMode


@dataclass(frozen=True, slots=True)
class DownloadCommandOptions:
    """Every `download` command-line value, typed once at the parsing boundary.

    Built directly from typer's already-validated values; nothing downstream re-casts a field with `int`, `bool` or `str`.
    """

    targets: tuple[str, ...]
    output: Path
    jobs: int
    connections: int
    timeout: float
    retries: int
    probe: ProbeMode
    overwrite: bool
    retry: bool
    yes: bool
    strict: bool
    metadata: bool
    archive: bool
    verbose: bool
    quiet: bool
