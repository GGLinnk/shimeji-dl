from pathlib import Path

from shimeji_dl.cli import _image_output_root, _merge_retry_results, _should_retry
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
