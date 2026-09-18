from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path

from . import __version__
from .client import AsyncFetcher, FetchError
from .downloader import DownloadOptions, Downloader
from .extractors import EXTRACTORS
from .models import CharacterRef

DEFAULT_USER_AGENT = f"shimeji-dl/{__version__} (+https://shimejis.xyz/)"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shimeji-dl",
        description="Async Shimeji downloader with extractor-style URL handling.",
    )
    parser.add_argument("targets", nargs="+", help="pack URL, character URL, or shimejis.xyz slug")
    parser.add_argument("-o", "--output", type=Path, default=Path("shimeji-downloads"))
    parser.add_argument("-j", "--jobs", type=_positive_int, default=5, help="characters downloaded concurrently (default: 5)")
    parser.add_argument("--connections", type=_positive_int, default=20, help="maximum concurrent HTTP requests (default: 20)")
    parser.add_argument("--timeout", type=_positive_float, default=20.0, help="HTTP timeout in seconds (default: 20)")
    parser.add_argument("--retries", type=_non_negative_int, default=3, help="HTTP retries (default: 3)")
    parser.add_argument(
        "--probe",
        choices=("auto", "off", "deep"),
        default="auto",
        help="numeric discovery: auto (default), off, or deeper sparse-tail exploration",
    )
    parser.add_argument("--no-probe", action="store_true", help="deprecated alias for --probe off")
    parser.add_argument("--force", action="store_true", help="redownload existing files")
    parser.add_argument("--strict", action="store_true", help="exit non-zero if a character is unusable or an XML-referenced image is missing")
    parser.add_argument("--no-metadata", action="store_true", help="do not write metadata.json")
    parser.add_argument("--archive", action="store_true", help="create <output>.zip after downloading")
    parser.add_argument("-v", "--verbose", action="store_true", help="show adaptive-probe details and attempted URLs")
    parser.add_argument("-q", "--quiet", action="store_true", help="only print fatal errors and final summary")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130) from None
    raise SystemExit(exit_code)


async def _run(args: argparse.Namespace) -> int:
    probe_mode = "off" if args.no_probe else args.probe
    async with AsyncFetcher(
        connections=args.connections,
        timeout=args.timeout,
        retries=args.retries,
        user_agent=args.user_agent,
    ) as fetcher:
        try:
            characters = await _extract_targets(fetcher, args.targets, quiet=args.quiet)
        except (ValueError, FetchError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

        options = DownloadOptions(
            output=args.output,
            jobs=args.jobs,
            probe_mode=probe_mode,
            force=args.force,
            metadata=not args.no_metadata,
            strict=args.strict,
            verbose=args.verbose,
            quiet=args.quiet,
        )
        downloader = Downloader(fetcher, options)
        results = await downloader.download_all(characters)

    usable = sum(result.usable for result in results)
    strict_failures = sum(not result.strict_ok for result in results)
    print(f"Finished: {usable}/{len(results)} usable character(s). Output: {args.output}", flush=True)

    if args.archive:
        archive = await asyncio.to_thread(_make_archive, args.output)
        print(f"Archive: {archive}", flush=True)

    if args.strict and strict_failures:
        return 1
    return 0 if usable == len(results) else 1


async def _extract_targets(fetcher: AsyncFetcher, targets: list[str], *, quiet: bool) -> list[CharacterRef]:
    async def extract_one(target: str) -> list[CharacterRef]:
        extractor_cls = next((candidate for candidate in EXTRACTORS if candidate.suitable(target)), None)
        if extractor_cls is None:
            raise ValueError(f"no extractor supports: {target}")
        if not quiet:
            print(f"extractor[{extractor_cls.key}]: {target}", flush=True)
        return await extractor_cls().extract(fetcher, target)

    groups = await asyncio.gather(*(extract_one(target) for target in targets))
    unique: list[CharacterRef] = []
    seen: set[tuple[str, str]] = set()
    for group in groups:
        for character in group:
            key = (character.extractor, character.id)
            if key in seen:
                continue
            seen.add(key)
            unique.append(character)
    return unique


def _make_archive(output: Path) -> Path:
    resolved = output.resolve()
    archive_base = resolved.parent / resolved.name
    archive_path = Path(shutil.make_archive(str(archive_base), "zip", root_dir=resolved.parent, base_dir=resolved.name))
    return archive_path


def _positive_int(value: str) -> int:
    integer = int(value)
    if integer <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return integer


def _non_negative_int(value: str) -> int:
    integer = int(value)
    if integer < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return integer


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return number
