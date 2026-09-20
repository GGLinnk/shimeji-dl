from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer

from ..archive import ArchiveRequest, ArchivingRefusal, build_archive
from ..core.confirmation import Confirmation, ask_for_confirmation
from ..core.engine import DownloadEngine, DownloadOptions
from ..core.error_description import describe_error
from ..core.http import HttpClient
from ..core.http_error import HttpError
from ..core.interfaces import SourceAdapter
from ..core.models import CharacterRef, CharacterResult
from ..formats.shimeji_xml import ShimejiXmlFormat
from ..sources.shimejis_xyz.target_vocabulary import pack_slug
from ..sources.target.registry import default_sources
from ..sources.target.target_kind import TargetKind
from ..sources.target.target_vocabularies import reduce_target
from ..ui import RichReporter
from ..version import get_version
from .confirmation_unavailable import ConfirmationUnavailable
from .download_options import DownloadCommandOptions
from .output_layout import image_output_root
from .probe_mode import ProbeMode
from .user_cancelled import UserCancelled


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
    archive: Annotated[
        bool,
        typer.Option(help="Archive each target into the output root after downloading."),
    ] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show probe and URL details.")] = False,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress progress output.")] = False,
) -> None:
    """Download one or more Shimeji targets into a Shimeji-compatible output root."""
    options = _build_download_options(
        targets=targets,
        output=output,
        jobs=jobs,
        connections=connections,
        timeout=timeout,
        retries=retries,
        probe=probe,
        overwrite=overwrite,
        retry=retry,
        yes=yes,
        strict=strict,
        metadata=metadata,
        archive=archive,
        verbose=verbose,
        quiet=quiet,
    )
    raise typer.Exit(asyncio.run(_run_download(options)))


def _build_download_options(
    *,
    targets: list[str],
    output: Path,
    jobs: int,
    connections: int,
    timeout: float,
    retries: int,
    probe: ProbeMode,
    overwrite: bool,
    retry: bool,
    yes: bool,
    strict: bool,
    metadata: bool,
    archive: bool,
    verbose: bool,
    quiet: bool,
) -> DownloadCommandOptions:
    return DownloadCommandOptions(
        targets=tuple(targets),
        output=output,
        jobs=jobs,
        connections=connections,
        timeout=timeout,
        retries=retries,
        probe=probe,
        overwrite=overwrite,
        retry=retry,
        yes=yes,
        strict=strict,
        metadata=metadata,
        archive=archive,
        verbose=verbose,
        quiet=quiet,
    )


async def _run_download(options: DownloadCommandOptions) -> int:
    reporter = RichReporter(quiet=options.quiet, verbose=options.verbose)
    sources = default_sources()
    user_agent = f"shimeji-dl/{get_version()}"

    async with HttpClient(
        connections=options.connections,
        timeout=options.timeout,
        retries=options.retries,
        user_agent=user_agent,
    ) as client:
        extraction_exit_code: int | None = None
        try:
            characters, extraction_by_target = await _extract_targets(
                client,
                sources,
                list(options.targets),
                reporter,
                assume_yes=options.yes,
            )
        except* UserCancelled:
            reporter.info("Cancelled.")
            extraction_exit_code = 0
        except* ConfirmationUnavailable as eg:
            for unavailable in eg.exceptions:
                reporter.fatal(str(unavailable))
            extraction_exit_code = 2
        except* (ValueError, HttpError) as eg:
            for error in eg.exceptions:
                reporter.fatal(describe_error(error))
            extraction_exit_code = 2
        if extraction_exit_code is not None:
            return extraction_exit_code

        image_root = image_output_root(options.output)
        download_options = DownloadOptions(
            output=image_root,
            jobs=options.jobs,
            probe_mode=options.probe.value,
            overwrite=options.overwrite,
            metadata=options.metadata,
            strict=options.strict,
        )
        engine = DownloadEngine(
            client,
            download_options,
            sources=sources,
            config_format=ShimejiXmlFormat(),
            reporter=reporter,
        )
        results = await engine.download_all(characters)

        failed = [result for result in results if result.retryable]
        if failed and _should_retry(
            reporter,
            len(failed),
            auto_retry=options.retry,
            assume_yes=options.yes,
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

    reporter.report_results(results, output=options.output)
    usable = sum(result.usable for result in results)
    strict_failures = sum(not result.strict_ok for result in results)

    archive_failed = False
    if options.archive:
        archive_failed = await _archive_each_target(
            image_root, options.output, extraction_by_target, reporter, assume_yes=options.yes
        )

    if options.strict and strict_failures:
        return 1
    if archive_failed:
        return 1
    return 0 if usable == len(results) else 1


async def _archive_each_target(
    image_root: Path,
    output_root: Path,
    extraction_by_target: list[tuple[str, list[CharacterRef]]],
    reporter: RichReporter,
    *,
    assume_yes: bool = False,
) -> bool:
    """Archive one target's own result set at a time; a failed target never aborts the others."""
    failed = False
    for target, characters in extraction_by_target:
        local = reduce_target(target)
        if local is None:
            name = target.strip()
        elif local.kind is TargetKind.COLLECTION:
            name = pack_slug(local.identifier)
        else:
            name = local.identifier
        request = ArchiveRequest(
            name=name,
            characters=tuple(image_root / character.id for character in characters),
        )
        try:
            await asyncio.to_thread(
                build_archive, image_root, output_root, request, reporter=reporter, assume_yes=assume_yes
            )
        except ArchivingRefusal as exc:
            reporter.fatal(str(exc))
            failed = True
    return failed


async def _extract_targets(
    client: HttpClient,
    sources: dict[str, SourceAdapter],
    targets: list[str],
    reporter: RichReporter,
    *,
    assume_yes: bool,
) -> tuple[list[CharacterRef], list[tuple[str, list[CharacterRef]]]]:
    resolved: list[tuple[SourceAdapter, str]] = []
    for target in targets:
        source = next((candidate for candidate in sources.values() if candidate.suitable(target)), None)
        if source is None:
            raise ValueError(f"no source supports: {target}")
        message = source.confirmation_message(target)
        if message and not assume_yes:
            outcome = ask_for_confirmation(reporter, message, default=False)
            if outcome is Confirmation.UNAVAILABLE:
                raise ConfirmationUnavailable(target)
            if outcome is Confirmation.DECLINED:
                raise UserCancelled()
        resolved.append((source, target))

    async def extract_one(source: SourceAdapter, target: str) -> list[CharacterRef]:
        reporter.extraction(source.key, target)
        return await source.extract(client, target)

    async with asyncio.TaskGroup() as task_group:
        tasks = [task_group.create_task(extract_one(source, target)) for source, target in resolved]
    character_groups = [task.result() for task in tasks]

    extraction_by_target = [
        (target, characters) for (_, target), characters in zip(resolved, character_groups, strict=True)
    ]

    unique: list[CharacterRef] = []
    seen: set[tuple[str, str]] = set()
    for characters in character_groups:
        for character in characters:
            key = (character.source, character.id)
            if key not in seen:
                seen.add(key)
                unique.append(character)
    return unique, extraction_by_target


def _should_retry(
    reporter: RichReporter,
    failed_count: int,
    *,
    auto_retry: bool,
    assume_yes: bool,
) -> bool:
    if auto_retry or assume_yes:
        return True
    outcome = ask_for_confirmation(reporter, f"Retry {failed_count} failed character(s)?", default=False)
    if outcome is Confirmation.UNAVAILABLE:
        reporter.warning(f"no confirmation could be asked: not retrying {failed_count} failed character(s)")
        return False
    return outcome is Confirmation.ACCEPTED


def _merge_retry_results(
    original: list[CharacterResult],
    retried: list[CharacterResult],
) -> list[CharacterResult]:
    replacements = {(result.character.source, result.character.id): result for result in retried}
    return [replacements.get((result.character.source, result.character.id), result) for result in original]
