import asyncio
import zipfile
from pathlib import Path

import pytest

from shimeji_dl.cli.archive import _run_archive
from shimeji_dl.cli.archive_options import ArchiveCommandOptions
from shimeji_dl.cli.download import (
    _archive_each_target,
    _extract_targets,
    _merge_retry_results,
    _should_retry,
)
from shimeji_dl.cli.output_layout import image_output_root
from shimeji_dl.core.error_description import describe_error
from shimeji_dl.core.models import CharacterRef, CharacterResult, ProbeReport
from shimeji_dl.sources.target.local_target import LocalTarget
from shimeji_dl.sources.target.target_kind import TargetKind
from shimeji_dl.sources.target.target_vocabularies import reduce_target


class ReporterStub:
    def __init__(self, answer: bool) -> None:
        self.answer = answer
        self.calls = 0

    def confirm(self, message: str, *, default: bool = False) -> bool:
        self.calls += 1
        return self.answer


def result(character_id: str, *, complete: bool) -> CharacterResult:
    return CharacterResult(
        character=CharacterRef("source", character_id, f"https://example/{character_id}"),
        output_dir=character_id,
        asset_paths=["shime1.png"] if complete else [],
        discovery="test",
        configs={},
        referenced_missing=[],
        probe=ProbeReport(mode="off"),
        usable=complete,
    )


def test_retry_flags_bypass_prompt() -> None:
    reporter = ReporterStub(False)
    assert _should_retry(reporter, 2, auto_retry=True, assume_yes=False)
    assert _should_retry(reporter, 2, auto_retry=False, assume_yes=True)
    assert reporter.calls == 0


def test_retry_prompt_is_used_without_flags() -> None:
    reporter = ReporterStub(True)
    assert _should_retry(reporter, 2, auto_retry=False, assume_yes=False)
    assert reporter.calls == 1


def test_retry_results_replace_only_retried_characters() -> None:
    first = [result("ok", complete=True), result("failed", complete=False)]
    retry = [result("failed", complete=True)]
    merged = _merge_retry_results(first, retry)
    assert merged[0] is first[0]
    assert merged[1] is retry[0]


def test_image_output_root_uses_native_shimeji_layout() -> None:
    assert image_output_root(Path("downloads")) == Path("downloads/img")
    assert image_output_root(Path("VShimeji/img")) == Path("VShimeji/img")


class _StubSource:
    key = "stub"

    def suitable(self, target: str) -> bool:
        return True

    def confirmation_message(self, target: str) -> str | None:
        return None

    async def extract(self, client: object, target: str) -> list[CharacterRef]:
        if target == "pack":
            return [
                CharacterRef("stub", "sans", "https://example/sans"),
                CharacterRef("stub", "papyrus", "https://example/papyrus"),
            ]
        return [CharacterRef("stub", target, f"https://example/{target}")]


def test_extract_targets_keeps_each_targets_own_character_group() -> None:
    """The per-target grouping feeds one archive per target.

    A pack's own characters must stay associated with the pack target that produced them, distinct from a character target passed in the same invocation.
    """
    source = _StubSource()
    reporter = _ExtractionReporterStub()

    async def run() -> tuple[list[CharacterRef], list[tuple[str, list[CharacterRef]]]]:
        return await _extract_targets(object(), {"stub": source}, ["pack", "sonic"], reporter, assume_yes=True)

    unique, by_target = asyncio.run(run())

    assert [character.id for character in unique] == ["sans", "papyrus", "sonic"]
    assert [target for target, _ in by_target] == ["pack", "sonic"]
    assert [character.id for character in by_target[0][1]] == ["sans", "papyrus"]
    assert [character.id for character in by_target[1][1]] == ["sonic"]


class _NestedFailureSource:
    """Mimics an adapter whose own internal TaskGroup (e.g. a multi-page
    extraction) wraps a leaf failure in its own ExceptionGroup before it ever
    reaches _extract_targets's TaskGroup."""

    key = "nested"

    def suitable(self, target: str) -> bool:
        return True

    def confirmation_message(self, target: str) -> str | None:
        return None

    async def extract(self, client: object, target: str) -> list[CharacterRef]:
        async def _raise() -> None:
            raise ValueError(f"no character links found in pack: {target}")

        async with asyncio.TaskGroup() as inner:
            inner.create_task(_raise())
        return []  # pragma: no cover - unreachable, the TaskGroup always re-raises first


class _ExtractionReporterStub:
    def extraction(self, source: str, target: str) -> None:
        pass

    def confirm(self, message: str, *, default: bool = False) -> bool:
        return True


def test_extract_targets_failure_nests_inside_two_task_groups() -> None:
    """describe_error must unpack every nesting level.

    Before this fix, cli.py's `except* (ValueError, HttpError) as eg` handler
    called `str(error)` on each of `eg.exceptions`, which is only the leaf
    ValueError when a source raises directly. When a source's own TaskGroup
    (as shimejis.xyz's page extraction does) wraps that ValueError first,
    `_extract_targets`'s TaskGroup nests it a second time, so `eg.exceptions[0]`
    is itself an ExceptionGroup and `str(error)` renders the useless
    "unhandled errors in a TaskGroup (1 sub-exception)" instead of the real
    message.
    """
    source = _NestedFailureSource()
    reporter = _ExtractionReporterStub()

    async def run() -> ExceptionGroup:
        with pytest.raises(ExceptionGroup) as excinfo:
            await _extract_targets(object(), {"nested": source}, ["pack"], reporter, assume_yes=True)
        return excinfo.value

    outer = asyncio.run(run())
    # The nesting is genuine: the immediate child is a group, not the leaf ValueError.
    assert isinstance(outer.exceptions[0], ExceptionGroup)

    messages = [describe_error(error) for error in outer.exceptions]
    assert messages == ["ValueError: no character links found in pack: pack"]


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("sans", LocalTarget(TargetKind.CHARACTER, "sans")),
        ("undertale-shimeji-pack", LocalTarget(TargetKind.COLLECTION, "undertale")),
        (
            "https://shimejis.xyz/directory/undertale-shimeji-pack",
            LocalTarget(TargetKind.COLLECTION, "undertale"),
        ),
        ("https://shimejis.xyz/directory/undertale", LocalTarget(TargetKind.COLLECTION, "undertale")),
        (
            "https://shimejis.xyz/directory/shimeji/sans",
            LocalTarget(TargetKind.CHARACTER, "sans"),
        ),
        ("shimejis.xyz", LocalTarget(TargetKind.SITE, "shimejis.xyz")),
        ("www.shimejis.xyz", LocalTarget(TargetKind.SITE, "shimejis.xyz")),
        ("https://shimejis.xyz", LocalTarget(TargetKind.SITE, "shimejis.xyz")),
        ("https://shimejis.xyz/directory", LocalTarget(TargetKind.SITE, "shimejis.xyz")),
        ("https://example.com/directory/shimeji/sans", None),
        ("Not A Slug!", None),
        ("http://[::1", None),
        ("Undertale", LocalTarget(TargetKind.CHARACTER, "undertale")),
    ],
)
def test_reduce_target_classifies_every_shape_shimejis_xyz_accepts(
    target: str,
    expected: LocalTarget | None,
) -> None:
    assert reduce_target(target) == expected


class _ArchiveReporterStub:
    def __init__(self) -> None:
        self.fatals: list[str] = []

    def archive_started(self, name: str, entry_count: int, byte_total: int) -> None:
        pass

    def archive_entry_written(self, entries_done: int, entry_count: int) -> None:
        pass

    def archive_finished(self, path: Path, entry_count: int, size: int) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def fatal(self, message: str) -> None:
        self.fatals.append(message)


def test_archive_each_target_names_a_pack_kind_target_by_its_pack_slug(tmp_path: Path) -> None:
    """A pack-shaped download target archives under the site's own pack slug, never the bare group identifier."""
    image_root = tmp_path / "img"
    for identifier in ("sans", "papyrus"):
        character_dir = image_root / identifier
        character_dir.mkdir(parents=True)
        (character_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    reporter = _ArchiveReporterStub()

    extraction_by_target = [
        (
            "https://shimejis.xyz/directory/undertale-shimeji-pack",
            [
                CharacterRef("stub", "sans", "https://example/sans"),
                CharacterRef("stub", "papyrus", "https://example/papyrus"),
            ],
        ),
    ]

    failed = asyncio.run(_archive_each_target(image_root, tmp_path, extraction_by_target, reporter))

    assert failed is False
    assert (tmp_path / "undertale-shimeji-pack.zip").exists()


def test_archive_each_target_continues_past_a_refused_target(tmp_path: Path) -> None:
    """One target's own naming refusal must never block a sibling target's archive."""
    image_root = tmp_path / "img"
    character_dir = image_root / "sans"
    character_dir.mkdir(parents=True)
    (character_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    reporter = _ArchiveReporterStub()

    extraction_by_target = [
        ("sans", [CharacterRef("stub", "sans", "https://example/sans")]),
        ("../evil", [CharacterRef("stub", "sans", "https://example/sans")]),
    ]

    failed = asyncio.run(_archive_each_target(image_root, tmp_path, extraction_by_target, reporter))

    assert failed is True
    assert (tmp_path / "sans.zip").exists()
    assert not (tmp_path.parent / "evil.zip").exists()
    assert reporter.fatals


def test_archive_each_target_continues_past_a_write_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A write failure on one target's archive must never abort a sibling target's own archive."""
    image_root = tmp_path / "img"
    for identifier in ("good", "bad"):
        character_dir = image_root / identifier
        character_dir.mkdir(parents=True)
        (character_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    reporter = _ArchiveReporterStub()

    real_write = zipfile.ZipFile.write

    def _fail_bad(self: zipfile.ZipFile, filename: object, arcname: str | None = None, *args: object) -> None:
        if arcname is not None and "img/bad" in arcname:
            raise OSError("disk full")
        real_write(self, filename, arcname, *args)

    monkeypatch.setattr(zipfile.ZipFile, "write", _fail_bad)

    extraction_by_target = [
        ("bad", [CharacterRef("stub", "bad", "https://example/bad")]),
        ("good", [CharacterRef("stub", "good", "https://example/good")]),
    ]

    failed = asyncio.run(_archive_each_target(image_root, tmp_path, extraction_by_target, reporter))

    assert failed is True
    assert (tmp_path / "good.zip").exists()
    assert not (tmp_path / "bad.zip").exists()
    assert list(tmp_path.glob("*.part")) == []
    assert reporter.fatals


def test_archive_each_target_continues_past_a_vanished_source_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A source entry deleted between listing and stat must never abort a sibling target's own archive."""
    image_root = tmp_path / "img"
    for identifier in ("good", "bad"):
        character_dir = image_root / identifier
        character_dir.mkdir(parents=True)
        (character_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    reporter = _ArchiveReporterStub()

    real_stat = Path.stat

    def _fail_bad(self: Path, *args: object, **kwargs: object) -> object:
        if "bad" in self.parts and self.name == "shime1.png":
            raise FileNotFoundError(2, "No such file or directory", str(self))
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", _fail_bad)

    extraction_by_target = [
        ("bad", [CharacterRef("stub", "bad", "https://example/bad")]),
        ("good", [CharacterRef("stub", "good", "https://example/good")]),
    ]

    failed = asyncio.run(_archive_each_target(image_root, tmp_path, extraction_by_target, reporter))

    assert failed is True
    assert (tmp_path / "good.zip").exists()
    assert not (tmp_path / "bad.zip").exists()
    assert reporter.fatals


def test_run_archive_builds_the_good_target_despite_a_sibling_write_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A write failure on one target's archive must never abort a sibling target's own archive."""
    image_root = tmp_path / "img"
    for identifier in ("good", "bad"):
        character_dir = image_root / identifier
        character_dir.mkdir(parents=True)
        (character_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    real_write = zipfile.ZipFile.write

    def _fail_bad(self: zipfile.ZipFile, filename: object, arcname: str | None = None, *args: object) -> None:
        if arcname is not None and "img/bad" in arcname:
            raise OSError("disk full")
        real_write(self, filename, arcname, *args)

    monkeypatch.setattr(zipfile.ZipFile, "write", _fail_bad)

    options = ArchiveCommandOptions(
        targets=("bad", "good"),
        output=tmp_path,
        verbose=False,
        quiet=True,
    )

    exit_code = asyncio.run(_run_archive(options))

    assert exit_code != 0
    assert (tmp_path / "good.zip").exists()
    assert not (tmp_path / "bad.zip").exists()
    assert list(tmp_path.glob("*.part")) == []


def test_run_archive_builds_the_good_target_despite_a_sibling_refusal(tmp_path: Path) -> None:
    """One target's own refusal must never block a sibling target's archive, nor mask the overall failure."""
    image_root = tmp_path / "img"
    good_dir = image_root / "good"
    good_dir.mkdir(parents=True)
    (good_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    options = ArchiveCommandOptions(
        targets=("good", "refused"),
        output=tmp_path,
        verbose=False,
        quiet=True,
    )

    exit_code = asyncio.run(_run_archive(options))

    assert exit_code != 0
    assert (tmp_path / "good.zip").exists()


def test_archive_command_resolves_a_url_target_against_the_local_directory(tmp_path: Path) -> None:
    """`archive` accepts a character URL, the same target shape `download` accepts."""
    image_root = tmp_path / "img"
    character_dir = image_root / "sans"
    character_dir.mkdir(parents=True)
    (character_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    options = ArchiveCommandOptions(
        targets=("https://shimejis.xyz/directory/shimeji/sans",),
        output=tmp_path,
        verbose=False,
        quiet=True,
    )

    exit_code = asyncio.run(_run_archive(options))

    assert exit_code == 0, list(tmp_path.iterdir())
    assert (tmp_path / "sans.zip").exists()


def test_archive_command_resolves_a_pack_url_target_by_its_pack_slug(tmp_path: Path) -> None:
    """`archive` accepts a pack URL and names the result by the site's own pack slug, never the bare group."""
    image_root = tmp_path / "img"
    character_dir = image_root / "sans"
    character_dir.mkdir(parents=True)
    (character_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (character_dir / "metadata.json").write_text(
        '{"source_adapter": "shimejis.xyz", "discovery": {"source_manifest": '
        '{"available": true, "metadata": {"group": "undertale", "groupName": "Undertale"}}}}',
        encoding="utf-8",
    )

    options = ArchiveCommandOptions(
        targets=("https://shimejis.xyz/directory/undertale-shimeji-pack",),
        output=tmp_path,
        verbose=False,
        quiet=True,
    )

    exit_code = asyncio.run(_run_archive(options))

    assert exit_code == 0, list(tmp_path.iterdir())
    assert (tmp_path / "undertale-shimeji-pack.zip").exists()


def test_quiet_archive_still_prints_the_warning_for_a_corrupt_sibling(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Quiet suppresses progress only; an unreadable document's warning must still reach the console."""
    image_root = tmp_path / "img"
    corrupt_dir = image_root / "sans"
    corrupt_dir.mkdir(parents=True)
    (corrupt_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (corrupt_dir / "metadata.json").write_text("{not valid json", encoding="utf-8")
    valid_dir = image_root / "papyrus"
    valid_dir.mkdir(parents=True)
    (valid_dir / "shime1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    options = ArchiveCommandOptions(targets=(), output=tmp_path, verbose=False, quiet=True)

    exit_code = asyncio.run(_run_archive(options))

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "unreadable metadata document" in output
    assert "sans" in output
