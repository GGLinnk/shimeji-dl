import asyncio
from pathlib import Path

import pytest

from shimeji_dl.cli import (
    _extract_targets,
    _image_output_root,
    _merge_retry_results,
    _should_retry,
)
from shimeji_dl.core.error_description import describe_error
from shimeji_dl.core.models import CharacterRef, CharacterResult, ProbeReport


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
    assert _image_output_root(Path("downloads")) == Path("downloads/img")
    assert _image_output_root(Path("VShimeji/img")) == Path("VShimeji/img")


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
