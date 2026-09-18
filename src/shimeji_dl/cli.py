from __future__ import annotations

import asyncio
import shutil
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from .core.engine import DownloadEngine, DownloadOptions
from .core.http import HttpClient, HttpError
from .formats.shimeji_xml import ShimejiXmlFormat
from .sources import default_sources
from .ui import RichReporter
from .version import get_version

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich")


class ProbeMode(str, Enum):
    AUTO = "auto"
    OFF = "off"
    DEEP = "deep"


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"shimeji-dl {get_version()}")
        raise typer.Exit()


@app.command()
def download(
    targets: Annotated[list[str], typer.Argument(help="Pack URL, character URL, or supported source identifier.")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Output directory.")] = Path("shimeji-downloads"),
    jobs: Annotated[int, typer.Option("--jobs", "-j", min=1, help="Characters downloaded concurrently.")] = 5,
    connections: Annotated[int, typer.Option(min=1, help="Maximum concurrent HTTP requests.")] = 20,
    timeout: Annotated[float, typer.Option(min=0.1, help="HTTP timeout in seconds.")] = 20.0,
    retries: Annotated[int, typer.Option(min=0, help="HTTP retries handled by Tenacity.")] = 3,
    probe: Annotated[ProbeMode, typer.Option(help="Adaptive numeric discovery mode.")] = ProbeMode.AUTO,
    force: Annotated[bool, typer.Option(help="Redownload existing files.")] = False,
    strict: Annotated[bool, typer.Option(help="Fail if a character is unusable or an XML-referenced asset is missing.")] = False,
    metadata: Annotated[bool, typer.Option("--metadata/--no-metadata", help="Write metadata.json.")] = True,
    archive: Annotated[bool, typer.Option(help="Create <output>.zip after downloading.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show probe and URL details.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress output.")] = False,
    version: Annotated[bool | None, typer.Option("--version", callback=_version_callback, is_eager=True)] = None,
) -> None:
    raise typer.Exit(asyncio.run(_run(
        targets=targets,
        output=output,
        jobs=jobs,
        connections=connections,
        timeout=timeout,
        retries=retries,
        probe=probe.value,
        force=force,
        strict=strict,
        metadata=metadata,
        archive=archive,
        verbose=verbose,
        quiet=quiet,
    )))


async def _run(**options: object) -> int:
    reporter = RichReporter(quiet=bool(options["quiet"]), verbose=bool(options["verbose"]))
    sources = default_sources()
    user_agent = f"shimeji-dl/{get_version()}"

    async with HttpClient(
        connections=int(options["connections"]),
        timeout=float(options["timeout"]),
        retries=int(options["retries"]),
        user_agent=user_agent,
    ) as client:
        try:
            characters = await _extract_targets(client, sources, list(options["targets"]), reporter)
        except (ValueError, HttpError) as exc:
            reporter.fatal(str(exc))
            return 2

        engine = DownloadEngine(
            client,
            DownloadOptions(
                output=Path(options["output"]),
                jobs=int(options["jobs"]),
                probe_mode=str(options["probe"]),
                force=bool(options["force"]),
                metadata=bool(options["metadata"]),
                strict=bool(options["strict"]),
            ),
            sources=sources,
            config_format=ShimejiXmlFormat(),
            reporter=reporter,
        )
        results = await engine.download_all(characters)

    usable = sum(result.usable for result in results)
    strict_failures = sum(not result.strict_ok for result in results)
    reporter.info(f"Finished: {usable}/{len(results)} usable character(s). Output: {options['output']}")

    if bool(options["archive"]):
        archive_path = await asyncio.to_thread(_make_archive, Path(options["output"]))
        reporter.info(f"Archive: {archive_path}")
    if bool(options["strict"]) and strict_failures:
        return 1
    return 0 if usable == len(results) else 1


async def _extract_targets(client: HttpClient, sources: dict[str, object], targets: list[str], reporter: RichReporter):
    async def extract_one(target: str):
        source = next((candidate for candidate in sources.values() if candidate.suitable(target)), None)
        if source is None:
            raise ValueError(f"no source supports: {target}")
        reporter.extraction(source.key, target)
        return await source.extract(client, target)

    groups = await asyncio.gather(*(extract_one(target) for target in targets))
    unique = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for character in group:
            key = (character.source, character.id)
            if key not in seen:
                seen.add(key)
                unique.append(character)
    return unique


def _make_archive(output: Path) -> Path:
    resolved = output.resolve()
    archive_base = resolved.parent / resolved.name
    return Path(shutil.make_archive(str(archive_base), "zip", root_dir=resolved.parent, base_dir=resolved.name))
