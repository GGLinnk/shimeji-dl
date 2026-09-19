from __future__ import annotations

import asyncio
import shutil
from dataclasses import replace
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from .core.engine import DownloadEngine, DownloadOptions
from .core.http import HttpClient, HttpError
from .core.interfaces import SourceAdapter
from .core.models import CharacterRef, CharacterResult
from .formats.shimeji_xml import ShimejiXmlFormat
from .sources import default_sources
from .ui import RichReporter
from .version import get_version

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich")


class ProbeMode(str, Enum):
    AUTO = "auto"
    OFF = "off"
    DEEP = "deep"


class UserCancelled(RuntimeError):
    pass


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"shimeji-dl {get_version()}")
        raise typer.Exit()


@app.command()
def download(
    targets: Annotated[list[str], typer.Argument(help="Pack URL, character URL, site URL, or supported source identifier.")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Shimeji-compatible output root; characters are stored under img/."),
    ] = Path("shimeji-downloads"),
    jobs: Annotated[int, typer.Option("--jobs", "-j", min=1, help="Characters downloaded concurrently.")] = 5,
    connections: Annotated[int, typer.Option(min=1, help="Maximum concurrent HTTP requests.")] = 20,
    timeout: Annotated[float, typer.Option(min=0.1, help="HTTP timeout in seconds.")] = 20.0,
    retries: Annotated[int, typer.Option(min=0, help="HTTP retries handled by Tenacity.")] = 3,
    probe: Annotated[ProbeMode, typer.Option(help="Adaptive numeric discovery mode.")] = ProbeMode.AUTO,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Redownload and replace existing valid files."),
    ] = False,
    retry: Annotated[
        bool,
        typer.Option("--retry", help="Automatically retry failed characters once."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Answer yes to all confirmation prompts."),
    ] = False,
    strict: Annotated[bool, typer.Option(help="Fail if a character is unusable or an XML-referenced asset is missing.")] = False,
    metadata: Annotated[bool, typer.Option("--metadata/--no-metadata", help="Write metadata.json.")] = True,
    archive: Annotated[bool, typer.Option(help="Create <output>.zip after downloading.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show probe and URL details.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress output.")] = False,
    version: Annotated[bool | None, typer.Option("--version", callback=_version_callback, is_eager=True)] = None,
) -> None:
    raise typer.Exit(
        asyncio.run(
            _run(
                targets=targets,
                output=output,
                jobs=jobs,
                connections=connections,
                timeout=timeout,
                retries=retries,
                probe=probe.value,
                overwrite=overwrite,
                retry=retry,
                yes=yes,
                strict=strict,
                metadata=metadata,
                archive=archive,
                verbose=verbose,
                quiet=quiet,
            )
        )
    )


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
            characters = await _extract_targets(
                client,
                sources,
                list(options["targets"]),
                reporter,
                assume_yes=bool(options["yes"]),
            )
        except UserCancelled:
            reporter.info("Cancelled.")
            return 0
        except (ValueError, HttpError) as exc:
            reporter.fatal(str(exc))
            return 2

        output_root = Path(options["output"])
        image_root = _image_output_root(output_root)
        download_options = DownloadOptions(
            output=image_root,
            jobs=int(options["jobs"]),
            probe_mode=str(options["probe"]),
            overwrite=bool(options["overwrite"]),
            metadata=bool(options["metadata"]),
            strict=bool(options["strict"]),
        )
        engine = DownloadEngine(
            client,
            download_options,
            sources=sources,
            config_format=ShimejiXmlFormat(),
            reporter=reporter,
        )
        results = await engine.download_all(characters)

        failed = [result for result in results if result.failed]
        if failed and _should_retry(
            reporter,
            len(failed),
            auto_retry=bool(options["retry"]),
            assume_yes=bool(options["yes"]),
        ):
            reporter.info(f"Retrying {len(failed)} failed character(s)...")
            retry_engine = DownloadEngine(
                client,
                replace(download_options, overwrite=False),
                sources=sources,
                config_format=ShimejiXmlFormat(),
                reporter=reporter,
            )
            retried = await retry_engine.download_all([result.character for result in failed])
            results = _merge_retry_results(results, retried)

    usable = sum(result.usable for result in results)
    complete = sum(result.complete for result in results)
    strict_failures = sum(not result.strict_ok for result in results)
    reporter.info(
        f"Finished: {usable}/{len(results)} usable, {complete}/{len(results)} complete character(s). "
        f"Output: {options['output']}"
    )

    if bool(options["archive"]):
        archive_path = await asyncio.to_thread(_make_archive, Path(options["output"]))
        reporter.info(f"Archive: {archive_path}")
    if bool(options["strict"]) and strict_failures:
        return 1
    return 0 if usable == len(results) else 1


async def _extract_targets(
    client: HttpClient,
    sources: dict[str, SourceAdapter],
    targets: list[str],
    reporter: RichReporter,
    *,
    assume_yes: bool,
) -> list[CharacterRef]:
    resolved: list[tuple[SourceAdapter, str]] = []
    for target in targets:
        source = next((candidate for candidate in sources.values() if candidate.suitable(target)), None)
        if source is None:
            raise ValueError(f"no source supports: {target}")
        message = source.confirmation_message(target)
        if message and not assume_yes and not reporter.confirm(message, default=False):
            raise UserCancelled()
        resolved.append((source, target))

    async def extract_one(source: SourceAdapter, target: str):
        reporter.extraction(source.key, target)
        return await source.extract(client, target)

    groups = await asyncio.gather(*(extract_one(source, target) for source, target in resolved))
    unique: list[CharacterRef] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for character in group:
            key = (character.source, character.id)
            if key not in seen:
                seen.add(key)
                unique.append(character)
    return unique


def _should_retry(
    reporter: RichReporter,
    failed_count: int,
    *,
    auto_retry: bool,
    assume_yes: bool,
) -> bool:
    if auto_retry or assume_yes:
        return True
    return reporter.confirm(f"Retry {failed_count} failed character(s)?", default=False)


def _merge_retry_results(
    original: list[CharacterResult],
    retried: list[CharacterResult],
) -> list[CharacterResult]:
    replacements = {(result.character.source, result.character.id): result for result in retried}
    return [replacements.get((result.character.source, result.character.id), result) for result in original]


def _image_output_root(output: Path) -> Path:
    return output if output.name.casefold() == "img" else output / "img"


def _make_archive(output: Path) -> Path:
    resolved = output.resolve()
    archive_base = resolved.parent / resolved.name
    return Path(shutil.make_archive(str(archive_base), "zip", root_dir=resolved.parent, base_dir=resolved.name))
