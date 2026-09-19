from io import StringIO

from rich.console import Console

from shimeji_dl.core.models import (
    CharacterRef,
    CharacterResult,
    MissingAsset,
    ProbeReport,
)
from shimeji_dl.ui.rich import RichReporter


def _result(character: CharacterRef, *, error: str | None = None) -> CharacterResult:
    return CharacterResult(
        character=character,
        output_dir="out",
        asset_paths=[] if error else ["shime1.png"],
        discovery="test",
        configs={},
        referenced_missing=[],
        probe=ProbeReport(mode="off"),
        usable=error is None,
        error=error,
    )


def test_progress_shows_only_active_viewport_and_promotes_hidden_tasks() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, height=5, force_terminal=False)
    reporter = RichReporter(console=console, error_console=console)
    characters = [CharacterRef("source", f"character-{index}", f"https://example/{index}") for index in range(4)]

    reporter.start(characters)
    assert len(reporter.progress.tasks) == 1

    for character in characters[:3]:
        reporter.character_started(character)

    descriptions = {task.description for task in reporter.progress.tasks}
    assert descriptions == {"Progress", "character-0", "character-1"}

    reporter.character_finished(_result(characters[0]))
    descriptions = {task.description for task in reporter.progress.tasks}
    assert descriptions == {"Progress", "character-1", "character-2"}
    reporter.finish()


def test_errors_are_reported_only_after_final_results() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(console=console, error_console=console)
    character = CharacterRef("source", "broken-character", "https://example")
    result = _result(character, error="boom")

    reporter.start([character])
    reporter.character_started(character)
    reporter.character_finished(result)
    reporter.finish()

    assert "boom" not in stream.getvalue()
    reporter.report_results([result])
    assert "broken-character: boom" in stream.getvalue()


def test_progress_folds_long_character_names_instead_of_ellipsis() -> None:
    stream = StringIO()
    console = Console(file=stream, width=42, force_terminal=False)
    reporter = RichReporter(console=console, error_console=console)
    character = CharacterRef("source", "undertale-a-very-very-long-character-name-that-must-not-be-ellipsized", "https://example")

    reporter.start([character])
    reporter.character_started(character)
    reporter.progress.refresh()
    reporter.finish()

    rendered = stream.getvalue()
    assert "..." not in rendered
    assert "ellipsized" in rendered


def test_missing_assets_are_aggregated_until_verbose_output() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(verbose=False, console=console, error_console=console)
    character = CharacterRef("source", "partial", "https://example")
    result = _result(character)
    result.referenced_missing = [
        MissingAsset("sound/one.wav", "source-missing", ("https://example/one.wav",)),
        MissingAsset("sound/two.wav", "source-missing", ("https://example/two.wav",)),
    ]

    reporter.report_results([result])

    rendered = stream.getvalue()
    assert "partial: 2 source-missing asset(s)" in rendered
    assert "sound/one.wav" not in rendered
