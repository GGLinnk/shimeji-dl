from io import StringIO

from rich.console import Console

from shimeji_dl.core.models import CharacterRef, CharacterResult, ProbeReport
from shimeji_dl.ui.rich import RichReporter


def test_progress_folds_long_character_names_instead_of_ellipsis() -> None:
    stream = StringIO()
    console = Console(file=stream, width=42, force_terminal=False)
    reporter = RichReporter(console=console, error_console=console)
    character = CharacterRef("source", "undertale-a-very-very-long-character-name-that-must-not-be-ellipsized", "https://example")
    reporter.start([character])
    reporter.character_finished(
        CharacterResult(
            character=character,
            output_dir="out",
            asset_paths=["shime1.png"],
            discovery="test",
            configs={},
            referenced_missing=[],
            probe=ProbeReport(mode="off"),
            usable=True,
        )
    )
    reporter.finish()
    rendered = stream.getvalue()
    assert "..." not in rendered
    assert "ellipsized" in rendered
