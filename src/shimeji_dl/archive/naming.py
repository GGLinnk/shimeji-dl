from __future__ import annotations

from pathlib import Path

from ..core.storage import validate_archive_name
from .refusals.archive_name_invalid import ArchiveNameInvalid

ARCHIVE_SUFFIX = ".zip"


def resolve_archive_path(output_root: Path, name: str) -> Path:
    """Validate a name and confine its archive file directly under the output root.

    `validate_archive_name` guarantees a validated name carries no path separator, so the join below can never leave `output_root`.
    """
    validated = validate_archive_name(name)
    if validated is None:
        raise ArchiveNameInvalid(name)
    return output_root / f"{validated}{ARCHIVE_SUFFIX}"
