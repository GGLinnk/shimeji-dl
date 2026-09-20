from io import StringIO

from rich.console import Console

from shimeji_dl.core.models import (
    CharacterRef,
    CharacterResult,
    MissingAsset,
    ProbeReport,
)
from shimeji_dl.sources.shimejis_xyz.manifest_rejection import InvalidSpritePath
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


def test_summary_task_total_and_completed_track_real_progress() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(console=console, error_console=console)
    characters = [CharacterRef("source", f"character-{index}", f"https://example/{index}") for index in range(3)]

    reporter.start(characters)
    summary = next(task for task in reporter.progress.tasks if task.description == "Progress")
    assert summary.total == len(characters)
    assert summary.completed == 0

    for character in characters:
        reporter.character_started(character)
        reporter.character_finished(_result(character))

    summary = next(task for task in reporter.progress.tasks if task.description == "Progress")
    assert summary.completed == len(characters)
    assert summary.total == len(characters)
    reporter.finish()


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


def test_verbose_output_escapes_markup_in_a_missing_asset_path() -> None:
    """An untrusted asset path can carry rich markup syntax.

    An unbalanced tag like "[/]" raises rich.errors.MarkupError out of the
    diagnostic path unless the reporter escapes it before printing.
    """
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(verbose=True, console=console, error_console=console)
    character = CharacterRef("source", "partial", "https://example")
    result = _result(character)
    result.referenced_missing = [MissingAsset("[/]evil.png", "source-missing", ())]

    reporter.report_results([result])

    assert "[/]evil.png" in stream.getvalue()


def test_verbose_output_escapes_markup_in_a_manifest_rejection_message() -> None:
    """A raw manifest key can carry rich markup syntax.

    manifest_rejection.py embeds the raw key verbatim in its message; the
    reporter, not the rejection, is responsible for escaping it before it
    reaches a markup-enabled console.
    """
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(verbose=True, console=console, error_console=console)
    rejection = InvalidSpritePath("[/]evil.png", b"null")

    reporter.verbose(str(rejection))

    assert "[/]evil.png" in stream.getvalue()


def test_fatal_escapes_markup_in_the_error_message() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(console=console, error_console=console)

    reporter.fatal("no source supports: [/]https://example.com")

    assert "[/]https://example.com" in stream.getvalue()
