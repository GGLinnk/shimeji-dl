from __future__ import annotations

from typing import Annotated

import typer

from ..version import get_version
from .archive import archive
from .download import download
from .group import DefaultCommandGroup

app = typer.Typer(
    cls=DefaultCommandGroup,
    add_completion=False,
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"shimeji-dl {get_version()}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[bool | None, typer.Option("--version", callback=_version_callback, is_eager=True)] = None,
) -> None:
    """Download Shimeji character packages, or archive what is already downloaded."""


app.command()(download)
app.command()(archive)
