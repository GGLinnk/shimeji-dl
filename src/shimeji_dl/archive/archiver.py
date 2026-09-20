from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..core.confirmation import Confirmation, ask_for_confirmation
from .naming import resolve_archive_path
from .refusals.archive_overwrite_refused import ArchiveOverwriteRefused
from .refusals.archive_source_unreadable import ArchiveSourceUnreadable
from .refusals.archive_write_failed import ArchiveWriteFailed
from .reporter import ArchiveReporter
from .request import ArchiveRequest
from .result import ArchiveResult


@dataclass(frozen=True, slots=True)
class _Entry:
    absolute: Path
    arcname: str
    is_dir: bool


def build_archive(
    image_root: Path,
    output_root: Path,
    request: ArchiveRequest,
    *,
    reporter: ArchiveReporter,
    assume_yes: bool = False,
) -> ArchiveResult:
    """Write one archive from an already-resolved request; the one owner both commands share.

    Every entry is written `.write()`-style directly from the character directories the request names: content never comes from walking the output root, so the archive being written can never include itself.
    An existing final file is confirmed before replacement, checked on the final path itself, before entry collection or any temporary file; `assume_yes` skips the prompt.
    """
    final_path = resolve_archive_path(output_root, request.name)
    try:
        already_exists = final_path.exists()
    except OSError as exc:
        raise ArchiveSourceUnreadable(final_path, exc) from exc
    if already_exists:
        _confirm_overwrite(final_path, reporter=reporter, assume_yes=assume_yes)

    try:
        entries = _collect_entries(image_root, request.characters)
        byte_total = sum(entry.absolute.stat().st_size for entry in entries if not entry.is_dir)
    except OSError as exc:
        raise ArchiveSourceUnreadable(_offending_path(exc, image_root), exc) from exc

    temp_path = final_path.with_name(final_path.name + ".part")

    reporter.archive_started(request.name, len(entries), byte_total)
    try:
        with zipfile.ZipFile(temp_path, mode="w", compression=zipfile.ZIP_DEFLATED, strict_timestamps=False) as archive:
            for done, entry in enumerate(entries, start=1):
                archive.write(entry.absolute, entry.arcname)
                reporter.archive_entry_written(done, len(entries))
        temp_path.replace(final_path)
    except BaseException as exc:
        temp_path.unlink(missing_ok=True)
        if isinstance(exc, OSError):
            raise ArchiveWriteFailed(final_path, exc) from exc
        raise

    try:
        size = final_path.stat().st_size
    except OSError as exc:
        raise ArchiveSourceUnreadable(final_path, exc) from exc
    reporter.archive_finished(final_path, len(entries), size)
    return ArchiveResult(final_path, len(entries), size)


def _confirm_overwrite(path: Path, *, reporter: ArchiveReporter, assume_yes: bool) -> None:
    """Ask before replacing an existing archive, through the one mechanism every confirmation site shares."""
    if assume_yes:
        return
    outcome = ask_for_confirmation(reporter, f"Archive already exists: {path}. Replace it?", default=False)
    if outcome is Confirmation.UNAVAILABLE:
        raise ArchiveOverwriteRefused(path, no_terminal=True)
    if outcome is Confirmation.DECLINED:
        raise ArchiveOverwriteRefused(path)


def _offending_path(exc: OSError, fallback: Path) -> Path:
    return Path(exc.filename) if exc.filename else fallback


def _collect_entries(image_root: Path, characters: tuple[Path, ...]) -> list[_Entry]:
    # Rooted at img/'s own parent, so img/ itself is always the archive's single top-level entry, extractable directly at an installation root.
    archive_base = image_root.parent
    entries: list[_Entry] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        arcname = path.relative_to(archive_base).as_posix()
        if arcname in seen:
            return
        seen.add(arcname)
        entries.append(_Entry(path, arcname, path.is_dir()))

    add(image_root)
    for character_dir in characters:
        add(character_dir)
        for member in sorted(_walk(character_dir)):
            add(member)
    return entries


def _raise_walk_error(exc: OSError) -> None:
    raise exc


def _walk(root: Path) -> list[Path]:
    """List every entry under `root`, recursively; unlike `Path.rglob`, an unreadable subtree's error propagates."""
    members: list[Path] = []
    for current, directories, files in os.walk(root, onerror=_raise_walk_error):
        current_path = Path(current)
        members.extend(current_path / name for name in directories)
        members.extend(current_path / name for name in files)
    return members
