from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from shimeji_dl.archive import (
    ArchiveNameInvalid,
    ArchiveOverwriteRefused,
    ArchiveSourceUnreadable,
    ArchiveWriteFailed,
    CharacterNotFound,
    CollectionNotFound,
    EmptyOutputRoot,
    MetadataState,
    MetadataWritingWasDisabled,
    NoCollectionRecorded,
    NoSourceRecorded,
    SourceNotFound,
    UnreadableMetadataDocument,
    UnsupportedTarget,
    build_archive,
    resolve_global,
    resolve_target,
)
from shimeji_dl.archive.local_character_index import build_local_character_index
from shimeji_dl.archive.metadata_read_model import CollectionIdentity
from shimeji_dl.core.storage import METADATA_FILENAME
from shimeji_dl.sources.shimejis_xyz.manifest_schema import ManifestMetadataWire


class _RecordingReporter:
    def __init__(
        self,
        *,
        confirm_answer: bool = True,
        can_confirm: bool = True,
        confirm_raises_eof: bool = False,
    ) -> None:
        self.started: tuple[str, int, int] | None = None
        self.entries_written = 0
        self.finished: tuple[Path, int, int] | None = None
        self.warnings: list[str] = []
        self.confirm_messages: list[str] = []
        self._confirm_answer = confirm_answer
        self._can_confirm = can_confirm
        self._confirm_raises_eof = confirm_raises_eof

    def archive_started(self, name: str, entry_count: int, byte_total: int) -> None:
        self.started = (name, entry_count, byte_total)

    def archive_entry_written(self, entries_done: int, entry_count: int) -> None:
        self.entries_written = entries_done

    def archive_finished(self, path: Path, entry_count: int, size: int) -> None:
        self.finished = (path, entry_count, size)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def confirm(self, message: str, *, default: bool = False) -> bool:
        self.confirm_messages.append(message)
        if self._confirm_raises_eof:
            raise EOFError("stdin closed while reading the confirmation")
        return self._confirm_answer

    def can_confirm(self) -> bool:
        return self._can_confirm


def _write_character(
    image_root: Path,
    identifier: str,
    *,
    group: str | None = None,
    group_name: str | None = None,
    source_adapter: str | None = "shimejis.xyz",
    with_metadata: bool = True,
    manifest_available: bool = True,
) -> Path:
    character_dir = image_root / identifier
    (character_dir / "conf").mkdir(parents=True)
    (character_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (character_dir / "conf" / "actions.xml").write_bytes(b"<Mascot/>")
    if with_metadata:
        source_manifest: dict[str, object] = {"available": manifest_available}
        if manifest_available:
            metadata: dict[str, object] = {}
            if group is not None:
                metadata["group"] = group
            if group_name is not None:
                metadata["groupName"] = group_name
            source_manifest["metadata"] = metadata
        payload = {
            "source_adapter": source_adapter,
            "discovery": {"source_manifest": source_manifest},
        }
        (character_dir / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    return character_dir


def _write_corrupt_character(image_root: Path, identifier: str) -> Path:
    character_dir = image_root / identifier
    (character_dir / "conf").mkdir(parents=True)
    (character_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (character_dir / "conf" / "actions.xml").write_bytes(b"<Mascot/>")
    (character_dir / "metadata.json").write_text("{not valid json", encoding="utf-8")
    return character_dir


def test_collection_identity_field_names_never_drift_from_the_manifest_wire() -> None:
    assert set(CollectionIdentity.__struct_fields__) <= set(ManifestMetadataWire.__struct_fields__)


def test_resolve_global_refuses_an_empty_output_root(tmp_path: Path) -> None:
    reporter = _RecordingReporter()
    with pytest.raises(EmptyOutputRoot):
        resolve_global(tmp_path / "img", tmp_path, reporter=reporter)


def test_resolve_global_covers_every_character(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale", group_name="Undertale")
    _write_character(image_root, "papyrus", group="undertale", group_name="Undertale")
    reporter = _RecordingReporter()

    request = resolve_global(image_root, tmp_path, reporter=reporter)

    assert request.name == tmp_path.name
    assert set(request.characters) == {image_root / "sans", image_root / "papyrus"}


def test_resolve_global_names_the_archive_after_the_resolved_output_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Path(".").name` is empty; the global archive name must come from the resolved directory instead."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    monkeypatch.chdir(tmp_path)
    reporter = _RecordingReporter()

    request = resolve_global(image_root, Path("."), reporter=reporter)

    assert request.name == tmp_path.name


def test_resolve_target_matches_a_character_directory_by_name(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)

    assert request.name == "sans"
    assert request.characters == (image_root / "sans",)


def test_resolve_target_character_kind_folds_case_like_the_collection_match_does(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "Sans")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)

    assert request.characters == (image_root / "Sans",)


def test_resolve_target_character_kind_prefers_its_directory_over_a_same_named_group(tmp_path: Path) -> None:
    """A bare character-shaped target must match its own directory first, never a collection sharing its name."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    _write_character(image_root, "papyrus", group="sans", group_name="Sans")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)

    assert request.characters == (image_root / "sans",)


def test_resolve_target_character_url_matches_its_directory(tmp_path: Path) -> None:
    """A character URL is unambiguous, so it matches its own directory only, never a same-named group."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    _write_character(image_root, "papyrus", group="sans", group_name="Sans")
    reporter = _RecordingReporter()

    request = resolve_target(
        image_root,
        tmp_path,
        "https://shimejis.xyz/directory/shimeji/sans",
        reporter=reporter,
    )

    assert request.characters == (image_root / "sans",)


def test_resolve_target_character_url_never_falls_through_to_a_same_named_group(tmp_path: Path) -> None:
    """A character URL with no matching directory must refuse as a character miss, never silently resolve to a same-named collection."""
    image_root = tmp_path / "img"
    _write_character(image_root, "papyrus", group="sans", group_name="Sans")
    reporter = _RecordingReporter()

    with pytest.raises(CharacterNotFound):
        resolve_target(
            image_root,
            tmp_path,
            "https://shimejis.xyz/directory/shimeji/sans",
            reporter=reporter,
        )


def test_resolve_target_character_url_refuses_the_same_way_whatever_the_metadata_state(tmp_path: Path) -> None:
    """A character miss is one cause regardless of unrelated metadata state, never a collection-cause refusal."""
    image_root = tmp_path / "img"
    _write_character(image_root, "papyrus", with_metadata=False)
    reporter = _RecordingReporter()

    with pytest.raises(CharacterNotFound):
        resolve_target(
            image_root,
            tmp_path,
            "https://shimejis.xyz/directory/shimeji/sans",
            reporter=reporter,
        )


def test_resolve_target_site_kind_refuses_with_a_source_not_found_cause(tmp_path: Path) -> None:
    """A site miss must name a source, never reuse the collection-cause refusal."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", source_adapter="other.site")
    reporter = _RecordingReporter()

    with pytest.raises(SourceNotFound) as excinfo:
        resolve_target(image_root, tmp_path, "shimejis.xyz", reporter=reporter)

    assert "source" in str(excinfo.value)


def test_resolve_target_site_kind_refuses_when_no_source_recorded(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", source_adapter=None)
    reporter = _RecordingReporter()

    with pytest.raises(NoSourceRecorded):
        resolve_target(image_root, tmp_path, "shimejis.xyz", reporter=reporter)


def test_resolve_target_site_kind_refuses_with_the_unreadable_document_cause(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_corrupt_character(image_root, "sans")
    reporter = _RecordingReporter()

    with pytest.raises(UnreadableMetadataDocument):
        resolve_target(image_root, tmp_path, "shimejis.xyz", reporter=reporter)


def test_resolve_target_site_kind_refuses_when_metadata_writing_was_disabled(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", with_metadata=False)
    reporter = _RecordingReporter()

    with pytest.raises(MetadataWritingWasDisabled):
        resolve_target(image_root, tmp_path, "shimejis.xyz", reporter=reporter)


def test_resolve_target_pack_kind_matches_the_collection_even_with_a_same_named_character_directory(
    tmp_path: Path,
) -> None:
    """A pack-shaped target must match by group only, never a character directory sharing its identifier."""
    image_root = tmp_path / "img"
    _write_character(image_root, "undertale")
    _write_character(image_root, "sans", group="undertale", group_name="Undertale")
    _write_character(image_root, "papyrus", group="undertale", group_name="Undertale")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "undertale-shimeji-pack", reporter=reporter)

    assert request.name == "undertale-shimeji-pack"
    assert set(request.characters) == {image_root / "sans", image_root / "papyrus"}


def test_resolve_target_pack_kind_refuses_with_the_collection_axis_ladder(tmp_path: Path) -> None:
    """The pack-shaped axis keeps its own dedicated classes, unaffected by the bare axis's own refusal type."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale")
    reporter = _RecordingReporter()

    with pytest.raises(CollectionNotFound):
        resolve_target(image_root, tmp_path, "nonexistent-shimeji-pack", reporter=reporter)


def test_resolve_target_pack_kind_refuses_when_no_manifest_was_available(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", manifest_available=False)
    reporter = _RecordingReporter()

    with pytest.raises(NoCollectionRecorded) as excinfo:
        resolve_target(image_root, tmp_path, "undertale-shimeji-pack", reporter=reporter)

    assert excinfo.value.state is MetadataState.NO_MANIFEST


def test_resolve_target_pack_kind_refuses_when_manifest_records_no_group(tmp_path: Path) -> None:
    """An available manifest recording no group is a distinct fact from no manifest at all."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", manifest_available=True, group=None, group_name=None)
    reporter = _RecordingReporter()

    with pytest.raises(NoCollectionRecorded) as excinfo:
        resolve_target(image_root, tmp_path, "undertale-shimeji-pack", reporter=reporter)

    assert excinfo.value.state is MetadataState.MANIFEST_WITHOUT_GROUP


def test_resolve_target_pack_kind_refuses_when_metadata_writing_was_disabled(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", with_metadata=False)
    reporter = _RecordingReporter()

    with pytest.raises(MetadataWritingWasDisabled):
        resolve_target(image_root, tmp_path, "undertale-shimeji-pack", reporter=reporter)


def test_resolve_target_pack_kind_refuses_with_the_unreadable_document_cause(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_corrupt_character(image_root, "sans")
    reporter = _RecordingReporter()

    with pytest.raises(UnreadableMetadataDocument):
        resolve_target(image_root, tmp_path, "undertale-shimeji-pack", reporter=reporter)


def test_resolve_target_site_kind_matches_by_source_adapter_even_with_a_same_named_character_directory(
    tmp_path: Path,
) -> None:
    """A site-shaped target must match by source_adapter only, never a character directory sharing its name."""
    image_root = tmp_path / "img"
    _write_character(image_root, "shimejis.xyz", source_adapter=None)
    _write_character(image_root, "sans", source_adapter="shimejis.xyz")
    _write_character(image_root, "sonic", source_adapter="shimejis.xyz")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "shimejis.xyz", reporter=reporter)

    assert request.name == "shimejis.xyz"
    assert set(request.characters) == {image_root / "sans", image_root / "sonic"}


def test_resolve_target_matches_a_collection_by_its_exact_display_name(tmp_path: Path) -> None:
    """The site's exact display name reaches the collection."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale", group_name="Undertale")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "Undertale", reporter=reporter)

    assert request.name == "undertale-shimeji-pack"
    assert request.characters == (image_root / "sans",)


def test_resolve_target_matches_a_multi_word_display_name_that_is_not_identifier_shaped(tmp_path: Path) -> None:
    """A display name with a space is not identifier-shaped; it still reaches the collection by exact text."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale", group_name="Not Undertale")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "Not Undertale", reporter=reporter)

    assert request.name == "undertale-shimeji-pack"
    assert request.characters == (image_root / "sans",)


def test_resolve_target_a_case_fold_of_a_display_name_never_matches_it(tmp_path: Path) -> None:
    """A case fold of a collection's exact display name never matches it: the refusal names the raw text tried."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale", group_name="Not Undertale")
    reporter = _RecordingReporter()

    with pytest.raises(CollectionNotFound) as excinfo:
        resolve_target(image_root, tmp_path, "not Undertale", reporter=reporter)

    assert excinfo.value.identifier == "not Undertale"


def test_resolve_target_a_non_identifier_shaped_miss_never_falls_back_to_a_character(tmp_path: Path) -> None:
    """Text that is not identifier-shaped is a display name only: a miss never tries a character lookup."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale", group_name="Undertale")
    reporter = _RecordingReporter()

    with pytest.raises(CollectionNotFound):
        resolve_target(image_root, tmp_path, "Not Undertale", reporter=reporter)


def test_resolve_target_lowercase_bare_identifier_never_falls_through_to_a_collection(tmp_path: Path) -> None:
    """An already-lowercase bare identifier is a character only: it never resolves a same-named collection."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale", group_name="Undertale")
    reporter = _RecordingReporter()

    with pytest.raises(CharacterNotFound):
        resolve_target(image_root, tmp_path, "undertale", reporter=reporter)


def test_resolve_target_lowercase_bare_identifier_matches_its_own_character_directory(tmp_path: Path) -> None:
    """The same bare identifier that never reaches a collection still matches its own character directory."""
    image_root = tmp_path / "img"
    _write_character(image_root, "undertale")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "undertale", reporter=reporter)

    assert request.name == "undertale"
    assert request.characters == (image_root / "undertale",)


def test_resolve_target_mixed_case_bare_identifier_falls_back_to_its_lowered_character(tmp_path: Path) -> None:
    """A mixed-case bare identifier with no matching display name still archives the character it lowers to."""
    image_root = tmp_path / "img"
    _write_character(image_root, "papyrus")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "Papyrus", reporter=reporter)

    assert request.name == "papyrus"
    assert request.characters == (image_root / "papyrus",)


def test_resolve_target_mixed_case_bare_identifier_prefers_the_display_name_over_the_lowered_character(
    tmp_path: Path,
) -> None:
    """The display-name attempt runs first: a same-named character directory never wins over a matching collection."""
    image_root = tmp_path / "img"
    _write_character(image_root, "undertale")
    _write_character(image_root, "sans", group="undertale", group_name="Undertale")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "Undertale", reporter=reporter)

    assert request.name == "undertale-shimeji-pack"
    assert request.characters == (image_root / "sans",)


def test_resolve_target_mixed_case_bare_identifier_refuses_by_its_lowered_character_name(tmp_path: Path) -> None:
    """With no matching display name and no lowered character directory, the refusal names the lowered form."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale", group_name="Not Undertale")
    reporter = _RecordingReporter()

    with pytest.raises(CharacterNotFound) as excinfo:
        resolve_target(image_root, tmp_path, "Undertale", reporter=reporter)

    assert excinfo.value.identifier == "undertale"


def test_resolve_target_matches_the_whole_site_by_source_adapter(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", source_adapter="shimejis.xyz")
    _write_character(image_root, "sonic", source_adapter="shimejis.xyz")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "shimejis.xyz", reporter=reporter)

    assert request.name == "shimejis.xyz"
    assert set(request.characters) == {image_root / "sans", image_root / "sonic"}


def test_resolve_target_refuses_a_malformed_url_instead_of_crashing(tmp_path: Path) -> None:
    """`urlsplit` raises `ValueError` on an unbalanced IPv6 literal; that must become a typed refusal, not a crash."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter()

    with pytest.raises(UnsupportedTarget) as excinfo:
        resolve_target(image_root, tmp_path, "http://[::1", reporter=reporter)

    assert "http://[::1" in str(excinfo.value)


def test_resolve_target_refuses_a_url_no_registered_source_accepts(tmp_path: Path) -> None:
    """A URL shaped for a foreign host must never be guessed at as a bare character slug."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter()

    with pytest.raises(UnsupportedTarget):
        resolve_target(image_root, tmp_path, "https://example.com/directory/shimeji/sans", reporter=reporter)


def test_resolve_target_reports_a_corrupt_document_and_still_matches_its_valid_sibling(tmp_path: Path) -> None:
    """A corrupt metadata.json must never silently drop its character from the archive without a trace."""
    image_root = tmp_path / "img"
    _write_corrupt_character(image_root, "sans")
    _write_character(image_root, "papyrus", group="undertale", group_name="Undertale")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "undertale-shimeji-pack", reporter=reporter)

    assert request.name == "undertale-shimeji-pack"
    assert request.characters == (image_root / "papyrus",)
    assert reporter.warnings
    assert "sans" in reporter.warnings[0]


def test_build_archive_roots_every_entry_at_the_parent_of_img(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans", group="undertale")
    reporter = _RecordingReporter()

    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)
    result = build_archive(image_root, tmp_path, request, reporter=reporter)

    assert result.path == tmp_path / "sans.zip"
    with zipfile.ZipFile(result.path) as archive:
        names = set(archive.namelist())
    assert "img/" in names
    assert "img/sans/" in names
    assert "img/sans/shime1.png" in names
    assert "img/sans/conf/actions.xml" in names
    assert reporter.started is not None
    assert reporter.finished is not None
    assert reporter.entries_written == reporter.started[1]


def test_build_archive_removes_its_part_file_when_a_write_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A write failure partway through must never leave a stray `.part` file behind, and must surface as a typed refusal."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter()
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)

    def _raise(self: zipfile.ZipFile, *args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(zipfile.ZipFile, "write", _raise)

    with pytest.raises(ArchiveWriteFailed) as excinfo:
        build_archive(image_root, tmp_path, request, reporter=reporter)

    assert isinstance(excinfo.value.__cause__, OSError)
    assert list(tmp_path.glob("*.part")) == []
    assert not (tmp_path / "sans.zip").exists()


def test_build_archive_reports_a_vanished_source_entry_as_a_typed_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source file removed between listing and stat must surface as a typed refusal, not a bare traceback."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter()
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)

    real_stat = Path.stat

    def _raise_for_png(self: Path, *args: object, **kwargs: object) -> object:
        if self.name == "shime1.png":
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _raise_for_png)

    with pytest.raises(ArchiveSourceUnreadable) as excinfo:
        build_archive(image_root, tmp_path, request, reporter=reporter)

    assert isinstance(excinfo.value.__cause__, OSError)


def test_build_archive_reports_an_unreadable_final_archive_as_a_typed_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A final-path stat failure after a successful write must surface as a typed refusal too."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter()
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)

    real_stat = Path.stat

    def _raise_for_zip(self: Path, *args: object, **kwargs: object) -> object:
        if self.suffix == ".zip":
            raise OSError("vanished after write")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _raise_for_zip)

    with pytest.raises(ArchiveSourceUnreadable) as excinfo:
        build_archive(image_root, tmp_path, request, reporter=reporter)

    assert isinstance(excinfo.value.__cause__, OSError)


def test_build_archive_reports_an_unreadable_character_subtree_as_a_typed_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`Path.rglob` swallows a per-subtree `PermissionError` silently; the walk used here must surface it instead."""
    image_root = tmp_path / "img"
    character_dir = _write_character(image_root, "sans")
    locked = character_dir / "locked"
    locked.mkdir()
    (locked / "shime2.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    reporter = _RecordingReporter()
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)

    real_scandir = os.scandir

    def _raise_for_locked(path: object = ".") -> object:
        if Path(path) == locked:
            raise PermissionError(13, "Permission denied", str(locked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", _raise_for_locked)

    with pytest.raises(ArchiveSourceUnreadable) as excinfo:
        build_archive(image_root, tmp_path, request, reporter=reporter)

    assert isinstance(excinfo.value.__cause__, OSError)
    assert excinfo.value.path == locked
    assert not (tmp_path / "sans.zip").exists()
    assert list(tmp_path.glob("*.part")) == []


def test_build_archive_clamps_a_pre_1980_mtime_instead_of_raising(tmp_path: Path) -> None:
    """`strict_timestamps=False` clamps a pre-1980 source mtime instead of raising a bare ValueError."""
    image_root = tmp_path / "img"
    character_dir = _write_character(image_root, "sans")
    epoch_1970 = 0
    os.utime(character_dir / "shime1.png", (epoch_1970, epoch_1970))
    reporter = _RecordingReporter()
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)

    result = build_archive(image_root, tmp_path, request, reporter=reporter)

    assert result.path.exists()


def test_build_local_character_index_reports_an_unreadable_root_as_a_typed_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A root that cannot be listed must surface as a typed refusal, not a bare traceback."""
    image_root = tmp_path / "img"
    image_root.mkdir()
    reporter = _RecordingReporter()

    def _raise(path: object) -> object:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "scandir", _raise)

    with pytest.raises(ArchiveSourceUnreadable) as excinfo:
        build_local_character_index(image_root, reporter=reporter)

    assert isinstance(excinfo.value.__cause__, OSError)


def test_build_local_character_index_ignores_is_dir_and_surfaces_the_real_scandir_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On 3.14+, `Path.is_dir` silently returns `False` on a permission error instead of raising.

    The index must never classify the root through it: only the guarded `os.scandir()` call may decide.
    """
    image_root = tmp_path / "img"
    image_root.mkdir()
    reporter = _RecordingReporter()

    monkeypatch.setattr(Path, "is_dir", lambda self: False)

    def _raise(path: object) -> object:
        raise PermissionError(13, "Permission denied", str(image_root))

    monkeypatch.setattr(os, "scandir", _raise)

    with pytest.raises(ArchiveSourceUnreadable) as excinfo:
        build_local_character_index(image_root, reporter=reporter)

    assert isinstance(excinfo.value.__cause__, OSError)


def test_build_local_character_index_reports_a_childs_stat_failure_as_a_typed_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child whose type cannot be read without a failing stat must surface as a typed refusal naming the root, never vanish from the index the way a `Path.is_dir`-based filter would let it.

    On 3.14+, `Path.is_dir` swallows the same `PermissionError` and reports `False` instead.
    """
    image_root = tmp_path / "img"
    image_root.mkdir()
    reporter = _RecordingReporter()

    class _RaisingEntry:
        name = "locked"
        path = str(image_root / "locked")

        def is_dir(self, *, follow_symlinks: bool = True) -> bool:
            raise PermissionError(13, "Permission denied", self.path)

    class _FakeScandirContext:
        def __enter__(self) -> list[_RaisingEntry]:
            return [_RaisingEntry()]

        def __exit__(self, *exc_info: object) -> None:
            return None

    monkeypatch.setattr(os, "scandir", lambda path: _FakeScandirContext())

    with pytest.raises(ArchiveSourceUnreadable) as excinfo:
        build_local_character_index(image_root, reporter=reporter)

    assert isinstance(excinfo.value.__cause__, OSError)
    assert excinfo.value.path == image_root


def test_read_character_ignores_is_file_and_surfaces_the_real_read_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On 3.14, `Path.is_file` silently returns `False` on a permission error instead of raising.

    The document read must never classify a metadata document as absent through it: only the read itself may decide.
    """
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter()

    monkeypatch.setattr(Path, "is_file", lambda self: False)
    real_read_bytes = Path.read_bytes

    def _raise_for_metadata(self: Path, *args: object, **kwargs: object) -> bytes:
        if self.name == METADATA_FILENAME:
            raise PermissionError(13, "Permission denied", str(self))
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", _raise_for_metadata)

    entries = build_local_character_index(image_root, reporter=reporter)

    assert len(entries) == 1
    assert entries[0].has_metadata_document is True
    assert entries[0].is_unreadable is True
    assert reporter.warnings


def test_build_archive_rejects_a_hostile_collection_name_and_never_escapes_the_root(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    character_dir = _write_character(image_root, "sans")
    reporter = _RecordingReporter()

    from shimeji_dl.archive.request import ArchiveRequest

    hostile_request = ArchiveRequest(name="../escape", characters=(character_dir,))
    with pytest.raises(ArchiveNameInvalid):
        build_archive(image_root, tmp_path, hostile_request, reporter=reporter)

    assert not (tmp_path.parent / "escape.zip").exists()
    assert list(tmp_path.iterdir()) == [image_root]


def test_build_archive_never_asks_when_no_archive_exists_yet(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter()
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)

    build_archive(image_root, tmp_path, request, reporter=reporter)

    assert reporter.confirm_messages == []


def test_build_archive_refuses_to_replace_an_existing_archive_without_confirmation(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter(confirm_answer=False)
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)
    existing = tmp_path / "sans.zip"
    existing.write_bytes(b"pre-existing archive bytes")
    original = existing.read_bytes()

    with pytest.raises(ArchiveOverwriteRefused) as excinfo:
        build_archive(image_root, tmp_path, request, reporter=reporter)

    assert excinfo.value.path == existing
    assert excinfo.value.no_terminal is False
    assert existing.read_bytes() == original
    assert list(tmp_path.glob("*.part")) == []
    assert reporter.confirm_messages
    assert str(existing) in reporter.confirm_messages[0]


def test_build_archive_replaces_an_existing_archive_after_confirmation(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter(confirm_answer=True)
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)
    existing = tmp_path / "sans.zip"
    existing.write_bytes(b"pre-existing archive bytes")

    result = build_archive(image_root, tmp_path, request, reporter=reporter)

    assert result.path == existing
    assert existing.read_bytes() != b"pre-existing archive bytes"
    with zipfile.ZipFile(existing) as archive:
        assert "img/sans/shime1.png" in archive.namelist()


def test_build_archive_with_assume_yes_replaces_without_asking(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter(confirm_answer=False, can_confirm=False)
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)
    existing = tmp_path / "sans.zip"
    existing.write_bytes(b"pre-existing archive bytes")

    result = build_archive(image_root, tmp_path, request, reporter=reporter, assume_yes=True)

    assert result.path == existing
    assert existing.read_bytes() != b"pre-existing archive bytes"
    assert reporter.confirm_messages == []


def test_build_archive_refuses_when_no_interactive_terminal_is_available(tmp_path: Path) -> None:
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter(can_confirm=False)
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)
    existing = tmp_path / "sans.zip"
    existing.write_bytes(b"pre-existing archive bytes")
    original = existing.read_bytes()

    with pytest.raises(ArchiveOverwriteRefused) as excinfo:
        build_archive(image_root, tmp_path, request, reporter=reporter)

    assert excinfo.value.path == existing
    assert excinfo.value.no_terminal is True
    assert "no confirmation could be asked" in str(excinfo.value)
    assert existing.read_bytes() == original
    assert reporter.confirm_messages == []


def test_build_archive_refuses_when_the_prompt_hits_eof_instead_of_an_answer(tmp_path: Path) -> None:
    """A terminal reported as interactive but closed mid-read must refuse typed, never crash bare."""
    image_root = tmp_path / "img"
    _write_character(image_root, "sans")
    reporter = _RecordingReporter(can_confirm=True, confirm_raises_eof=True)
    request = resolve_target(image_root, tmp_path, "sans", reporter=reporter)
    existing = tmp_path / "sans.zip"
    existing.write_bytes(b"pre-existing archive bytes")
    original = existing.read_bytes()

    with pytest.raises(ArchiveOverwriteRefused) as excinfo:
        build_archive(image_root, tmp_path, request, reporter=reporter)

    assert excinfo.value.path == existing
    assert excinfo.value.no_terminal is True
    assert existing.read_bytes() == original
