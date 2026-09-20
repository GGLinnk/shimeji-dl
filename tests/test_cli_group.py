from __future__ import annotations

import pytest
from typer.testing import CliRunner

from shimeji_dl.cli import app
from shimeji_dl.cli import archive as archive_module
from shimeji_dl.cli import download as download_module
from shimeji_dl.cli.archive_options import ArchiveCommandOptions
from shimeji_dl.cli.download_options import DownloadCommandOptions

runner = CliRunner()


@pytest.fixture
def recorded_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, object]]:
    calls: list[tuple[str, object]] = []

    async def fake_download(options: DownloadCommandOptions) -> int:
        calls.append(("download", options))
        return 0

    async def fake_archive(options: ArchiveCommandOptions) -> int:
        calls.append(("archive", options))
        return 0

    monkeypatch.setattr(download_module, "_run_download", fake_download)
    monkeypatch.setattr(archive_module, "_run_archive", fake_archive)
    return calls


@pytest.mark.parametrize(
    ("args", "expected_command", "expected_targets"),
    [
        (["undertale-sans"], "download", ("undertale-sans",)),
        (["--jobs", "3", "undertale-sans"], "download", ("undertale-sans",)),
        (["-j", "3", "undertale-sans"], "download", ("undertale-sans",)),
        (["--jobs=3", "undertale-sans"], "download", ("undertale-sans",)),
        (["-o", "out", "undertale-sans"], "download", ("undertale-sans",)),
        (["--output", "out", "undertale-sans"], "download", ("undertale-sans",)),
        (["archive"], "archive", ()),
        (["archive", "undertale-sans"], "archive", ("undertale-sans",)),
        (["download", "archive"], "download", ("archive",)),
    ],
)
def test_default_command_group_routes_every_invocation_shape(
    recorded_calls: list[tuple[str, object]],
    args: list[str],
    expected_command: str,
    expected_targets: tuple[str, ...],
) -> None:
    result = runner.invoke(app, args, prog_name="shimeji-dl")

    assert result.exit_code == 0, result.output
    assert len(recorded_calls) == 1
    command, options = recorded_calls[0]
    assert command == expected_command
    assert options.targets == expected_targets


def test_bare_target_named_like_a_command_is_read_as_the_command(recorded_calls: list[tuple[str, object]]) -> None:
    """A target that collides with a command name resolves to the command.

    The documented fallback is naming `download` explicitly, covered separately.
    """
    result = runner.invoke(app, ["archive"], prog_name="shimeji-dl")

    assert result.exit_code == 0, result.output
    assert recorded_calls[0][0] == "archive"


def test_download_with_no_target_reports_the_missing_argument(recorded_calls: list[tuple[str, object]]) -> None:
    result = runner.invoke(app, ["download"], prog_name="shimeji-dl")

    assert result.exit_code == 2
    assert "Missing argument" in result.output
    assert not recorded_calls


def test_unknown_option_is_reported_inside_the_download_context(recorded_calls: list[tuple[str, object]]) -> None:
    result = runner.invoke(app, ["--bogus"], prog_name="shimeji-dl")

    assert result.exit_code != 0
    assert "shimeji-dl download" in result.output
    assert not recorded_calls


def test_bare_invocation_shows_group_help(recorded_calls: list[tuple[str, object]]) -> None:
    result = runner.invoke(app, [], prog_name="shimeji-dl")

    assert "Usage: shimeji-dl" in result.output
    assert "download" in result.output
    assert "archive" in result.output
    assert not recorded_calls


def test_group_help_flag_lists_both_commands(recorded_calls: list[tuple[str, object]]) -> None:
    result = runner.invoke(app, ["--help"], prog_name="shimeji-dl")

    assert result.exit_code == 0
    assert "download" in result.output
    assert "archive" in result.output
    assert not recorded_calls


def test_download_help_flag_shows_only_download_usage(recorded_calls: list[tuple[str, object]]) -> None:
    result = runner.invoke(app, ["download", "--help"], prog_name="shimeji-dl")

    assert result.exit_code == 0
    assert "shimeji-dl download" in result.output
    assert not recorded_calls


def test_archive_help_flag_shows_only_archive_usage(recorded_calls: list[tuple[str, object]]) -> None:
    result = runner.invoke(app, ["archive", "--help"], prog_name="shimeji-dl")

    assert result.exit_code == 0
    assert "shimeji-dl archive" in result.output
    assert not recorded_calls


def test_version_flag_prints_the_version_without_any_subcommand(recorded_calls: list[tuple[str, object]]) -> None:
    result = runner.invoke(app, ["--version"], prog_name="shimeji-dl")

    assert result.exit_code == 0
    assert result.output.startswith("shimeji-dl ")
    assert not recorded_calls


def test_download_command_receives_typed_options_not_strings(recorded_calls: list[tuple[str, object]]) -> None:
    result = runner.invoke(
        app,
        ["--jobs", "7", "--overwrite", "--probe", "deep", "undertale-sans"],
        prog_name="shimeji-dl",
    )

    assert result.exit_code == 0, result.output
    _, options = recorded_calls[0]
    assert isinstance(options, DownloadCommandOptions)
    assert isinstance(options.jobs, int) and options.jobs == 7
    assert isinstance(options.overwrite, bool) and options.overwrite is True
    assert options.probe.value == "deep"


def test_archive_command_receives_typed_options_not_strings(recorded_calls: list[tuple[str, object]]) -> None:
    result = runner.invoke(app, ["archive", "--quiet"], prog_name="shimeji-dl")

    assert result.exit_code == 0, result.output
    _, options = recorded_calls[0]
    assert isinstance(options, ArchiveCommandOptions)
    assert isinstance(options.quiet, bool) and options.quiet is True
