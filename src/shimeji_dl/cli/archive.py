from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from ..archive import ArchivingRefusal, build_archive, resolve_global, resolve_target
from ..ui import RichReporter
from .archive_options import ArchiveCommandOptions
from .output_layout import image_output_root


def archive(
    targets: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "Character identifier, collection pack slug or display name, or URL "
                "reduced to its local form. Omit for the whole output root."
            )
        ),
    ] = None,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Shimeji-compatible output root to archive from."),
    ] = Path("shimeji-downloads"),
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Answer yes to all confirmation prompts."),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show matched-character details.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress output.")] = False,
) -> None:
    """Archive what is already downloaded, without any network access.

    With no target, archives the whole output root: the only command allowed to produce that unnamed, global archive.
    """
    options = ArchiveCommandOptions(
        targets=tuple(targets or []),
        output=output,
        verbose=verbose,
        quiet=quiet,
        yes=yes,
    )
    raise typer.Exit(asyncio.run(_run_archive(options)))


async def _run_archive(options: ArchiveCommandOptions) -> int:
    reporter = RichReporter(quiet=options.quiet, verbose=options.verbose)
    image_root = image_output_root(options.output)

    if not options.targets:
        return await _resolve_and_build(
            image_root, options.output, None, reporter, verbose=options.verbose, assume_yes=options.yes
        )

    failed = False
    for target in options.targets:
        exit_code = await _resolve_and_build(
            image_root, options.output, target, reporter, verbose=options.verbose, assume_yes=options.yes
        )
        if exit_code != 0:
            failed = True
    return 1 if failed else 0


async def _resolve_and_build(
    image_root: Path,
    output_root: Path,
    target: str | None,
    reporter: RichReporter,
    *,
    verbose: bool,
    assume_yes: bool = False,
) -> int:
    """Resolve and build one target's own archive; a refusal here never blocks a sibling target."""
    try:
        request = (
            resolve_global(image_root, output_root, reporter=reporter)
            if target is None
            else resolve_target(image_root, output_root, target, reporter=reporter)
        )
    except ArchivingRefusal as exc:
        reporter.fatal(str(exc))
        return 2

    if verbose:
        reporter.verbose(f"archiving {request.name}: {len(request.characters)} character(s)")
    try:
        await asyncio.to_thread(build_archive, image_root, output_root, request, reporter=reporter, assume_yes=assume_yes)
    except ArchivingRefusal as exc:
        reporter.fatal(str(exc))
        return 1
    return 0
