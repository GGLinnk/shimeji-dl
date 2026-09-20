from io import StringIO
from pathlib import Path

import pytest
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


def test_summary_completed_count_reflects_every_finished_character() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(console=console, error_console=console)
    characters = [CharacterRef("source", f"character-{index}", f"https://example/{index}") for index in range(3)]

    reporter.start(characters)
    for character in characters:
        reporter.character_finished(_result(character))

    summary_task = next(task for task in reporter.progress.tasks if task.description == "Progress")
    assert "3/3 done" in summary_task.fields["phase"]
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
    reporter.report_results([result], output=Path("out"))
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

    reporter.report_results([result], output=Path("out"))

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

    reporter.report_results([result], output=Path("out"))

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
    rejection = InvalidSpritePath("[/]evil.png")

    reporter.verbose(str(rejection))

    assert "[/]evil.png" in stream.getvalue()


def test_fatal_escapes_markup_in_the_error_message() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(console=console, error_console=console)

    reporter.fatal("no source supports: [/]https://example.com")

    assert "[/]https://example.com" in stream.getvalue()


def test_warning_prints_even_when_quiet() -> None:
    """Quiet suppresses progress and informational output only; a warning always prints."""
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(quiet=True, console=console, error_console=console)

    reporter.warning("unreadable metadata document: sans")

    assert "unreadable metadata document: sans" in stream.getvalue()


def test_report_results_prints_the_issue_list_even_when_quiet() -> None:
    """The end-of-pass report has no quiet exception, per the product feature on reporting errors at the end."""
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(quiet=True, console=console, error_console=console)
    character = CharacterRef("source", "broken-character", "https://example")
    result = _result(character, error="boom")

    reporter.report_results([result], output=Path("out"))

    output = stream.getvalue()
    assert "Issues:" in output
    assert "broken-character: boom" in output


def test_report_results_prints_per_item_rejections_even_when_quiet() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(quiet=True, console=console, error_console=console)
    character = CharacterRef("source", "partial", "https://example")
    result = _result(character)
    result.referenced_missing = [MissingAsset("sound/one.wav", "source-missing", ("https://example/one.wav",))]

    reporter.report_results([result], output=Path("out"))

    assert "partial: 1 source-missing asset(s)" in stream.getvalue()


def test_quiet_download_pass_still_prints_its_end_of_pass_report(capsys: pytest.CaptureFixture[str]) -> None:
    """Constructed exactly as `_run_download` builds it, with no injected console, so capsys binds to its real stdout."""
    reporter = RichReporter(quiet=True)
    character = CharacterRef("source", "broken-character", "https://example")
    result = _result(character, error="boom")

    reporter.report_results([result], output=Path("shimeji-downloads"))

    output = capsys.readouterr().out
    assert "Issues:" in output
    assert "broken-character: boom" in output
    assert "Finished: 0/1 usable" in output


def test_archive_progress_announces_and_reports_size_even_when_quiet() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(quiet=True, console=console, error_console=console)

    archive_path = Path("shimeji-downloads") / "undertale.zip"
    reporter.archive_started("undertale", 3, 42)
    reporter.archive_entry_written(1, 3)
    reporter.archive_finished(archive_path, 3, 2048)

    output = stream.getvalue()
    assert "undertale" in output
    assert str(archive_path) in output
    assert "2.0 KiB" in output
    assert reporter._archive_progress is None


def test_archive_progress_bar_is_created_and_torn_down_when_not_quiet() -> None:
    stream = StringIO()
    console = Console(file=stream, width=80, force_terminal=False)
    reporter = RichReporter(console=console, error_console=console)

    reporter.archive_started("undertale", 3, 42)
    assert reporter._archive_progress is not None
    reporter.archive_entry_written(2, 3)
    reporter.archive_finished(Path("shimeji-downloads") / "undertale.zip", 3, 2048)

    assert reporter._archive_progress is None


def test_can_confirm_reflects_whether_stdin_is_a_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    reporter = RichReporter()

    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert reporter.can_confirm() is False

    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    assert reporter.can_confirm() is True


def test_confirm_never_prompts_when_it_cannot_confirm(monkeypatch: pytest.MonkeyPatch) -> None:
    """`confirm` defers to `can_confirm`: no interactive terminal means no prompt is shown, just a refusal."""
    reporter = RichReporter()
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    def _fail_if_asked(*args: object, **kwargs: object) -> bool:
        raise AssertionError("confirm must not prompt when can_confirm() is False")

    monkeypatch.setattr("shimeji_dl.ui.rich.Confirm.ask", _fail_if_asked)

    assert reporter.confirm("Replace it?") is False


def test_confirm_escapes_markup_in_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """A validated archive name can carry a bracket segment; the question must show it verbatim, not as markup."""
    from rich.text import Text

    reporter = RichReporter()
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    captured: dict[str, str] = {}

    def _capture(prompt: str, *, default: bool = False, console: object = None) -> bool:
        captured["prompt"] = prompt
        return True

    monkeypatch.setattr("shimeji_dl.ui.rich.Confirm.ask", _capture)

    message = "Archive already exists: shimeji-downloads/a[b]-shimeji-pack.zip. Replace it?"
    reporter.confirm(message)

    assert Text.from_markup(captured["prompt"]).plain == message


def test_can_confirm_is_false_when_stdin_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """A closed file descriptor 0 (`<&-`) leaves `sys.stdin` as `None`: never an AttributeError."""
    reporter = RichReporter()
    monkeypatch.setattr("sys.stdin", None)

    assert reporter.can_confirm() is False


def test_can_confirm_is_false_when_isatty_itself_raises_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    reporter = RichReporter()

    def _raise() -> bool:
        raise OSError("bad file descriptor")

    monkeypatch.setattr("sys.stdin.isatty", _raise)

    assert reporter.can_confirm() is False


def test_can_confirm_is_false_when_stdin_is_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A closed stream's `isatty()` raises `ValueError`, not `OSError`: checked before ever calling it."""
    reporter = RichReporter()
    closed_stream = StringIO()
    closed_stream.close()
    monkeypatch.setattr("sys.stdin", closed_stream)

    assert reporter.can_confirm() is False
