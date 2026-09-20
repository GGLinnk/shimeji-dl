from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import msgspec

from ..core.storage import METADATA_FILENAME
from .metadata_read_model import CharacterMetadataRecord
from .refusals.archive_source_unreadable import ArchiveSourceUnreadable
from .reporter import ArchiveReporter


@dataclass(frozen=True, slots=True)
class CharacterEntry:
    """One downloaded character directory, with whatever collection identity it recorded."""

    directory: Path
    group: str | None
    group_name: str | None
    source_adapter: str | None
    has_metadata_document: bool
    manifest_available: bool = False
    is_unreadable: bool = False


def build_local_character_index(image_root: Path, *, reporter: ArchiveReporter) -> list[CharacterEntry]:
    # os.scandir's entry.is_dir() reads the entry's own directory bit; unlike Path.is_dir, it cannot silently turn a permission error on one child into "not a directory" on 3.14+.
    try:
        with os.scandir(image_root) as it:
            directories = sorted(Path(entry.path) for entry in it if entry.is_dir())
    except (FileNotFoundError, NotADirectoryError):
        # An absent or non-directory root carries no characters, distinct from an unreadable one.
        return []
    except OSError as exc:
        raise ArchiveSourceUnreadable(image_root, exc) from exc
    return [_read_character(directory, reporter) for directory in directories]


def _read_character(directory: Path, reporter: ArchiveReporter) -> CharacterEntry:
    metadata_path = directory / METADATA_FILENAME
    try:
        raw = metadata_path.read_bytes()
        record = msgspec.json.decode(raw, type=CharacterMetadataRecord)
    except FileNotFoundError:
        return CharacterEntry(directory, None, None, None, has_metadata_document=False)
    except (OSError, msgspec.DecodeError) as exc:
        reporter.warning(f"unreadable metadata document, excluded from collection matching: {directory.name}: {exc}")
        return CharacterEntry(directory, None, None, None, has_metadata_document=True, is_unreadable=True)

    manifest_available = False
    identity = None
    if record.discovery is not None and record.discovery.source_manifest is not None:
        manifest_available = record.discovery.source_manifest.available
        identity = record.discovery.source_manifest.metadata
    return CharacterEntry(
        directory,
        identity.group if identity else None,
        identity.groupName if identity else None,
        record.source_adapter,
        has_metadata_document=True,
        manifest_available=manifest_available,
    )
