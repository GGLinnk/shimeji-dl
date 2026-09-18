from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from dataclasses import asdict
import sys

from rich.console import Console
from rich.table import Table

from . import __version__
from .downloader import CharacterDownloader
from .errors import ShimejiDLError
from .extractors import ShimejisXYZExtractor
from .http import AsyncHTTP
from .models import Character, CharacterReport
from .utils import character_folder_name, safe_folder_name

console = Console(stderr=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="shimeji-dl",
        description="Async downloader for shimejis.xyz, with VShimeji-compatible output.",
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Pack URL, character URL, or shimejis.xyz character slug.",
    )
    out = parser.add_mutually_exclusive_group()
    out.add_argument("-o", "--output", type=Path, default=Path("shimeji-downloads"))
    out.add_argument(
        "--vshimeji",
        type=Path,
        help="VShimeji root directory. Characters are written under <path>/img/.",
    )
    parser.add_argument("-j", "--jobs", type=int, default=4, help="Characters processed concurrently.")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=12,
        help="Maximum concurrent HTTP requests across all characters.",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument(
        "--probe-max",
        type=int,
        default=128,
        help="When XML is unavailable, exhaustively try shime1.png..shimeN.png (default: 128).",
    )
    parser.add_argument(
        "--scan-extras",
        action="store_true",
        help="Even when actions.xml exists, also probe shime1.png..shimeN.png for unused extras.",
    )
    parser.add_argument("--no-config", action="store_true", help="Do not try actions/behaviors XML.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Extract inputs and print characters without downloading.",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _dedupe(chars: list[Character]) -> list[Character]:
    result: list[Character] = []
    seen: set[str] = set()
    for char in chars:
        if char.slug not in seen:
            seen.add(char.slug)
            result.append(char)
    return result


def _allocate_destinations(chars: list[Character], root: Path) -> dict[str, Path]:
    used: set[str] = set()
    result: dict[str, Path] = {}
    for char in chars:
        base = character_folder_name(char.slug, char.name, char.artist)
        name = base
        if name.casefold() in used:
            name = safe_folder_name(f"{base} [{char.slug}]")
        used.add(name.casefold())
        result[char.slug] = root / name
    return result


async def async_main(args: argparse.Namespace) -> int:
    if args.jobs < 1 or args.concurrency < 1 or args.probe_max < 1:
        raise ShimejiDLError("--jobs, --concurrency and --probe-max must be >= 1")

    output_root = (args.vshimeji / "img") if args.vshimeji else args.output

    async with AsyncHTTP(
        concurrency=args.concurrency,
        timeout=args.timeout,
        retries=args.retries,
    ) as http:
        extractor = ShimejisXYZExtractor(http)
        chars: list[Character] = []
        for value in args.inputs:
            console.print(f"[cyan]extractor:[/cyan] {value}", highlight=False)
            chars.extend(await extractor.extract(value))
        chars = _dedupe(chars)

        if args.list_only:
            if args.json:
                print(json.dumps([asdict(char) for char in chars], ensure_ascii=False, indent=2))
            else:
                table = Table(title=f"{len(chars)} character(s)")
                table.add_column("Slug")
                table.add_column("Name")
                table.add_column("Artist")
                for char in chars:
                    table.add_row(char.slug, char.name or "", char.artist or "")
                console.print(table)
            return 0

        destinations = _allocate_destinations(chars, output_root)
        downloader = CharacterDownloader(
            http,
            extractor,
            overwrite=args.overwrite,
            probe_max=args.probe_max,
            scan_extras=args.scan_extras,
            no_config=args.no_config,
            dry_run=args.dry_run,
        )

        job_sem = asyncio.Semaphore(args.jobs)

        async def run_one(char: Character) -> CharacterReport:
            async with job_sem:
                console.print(f"[blue]download:[/blue] {char.slug}", highlight=False)
                return await downloader.download(char, destinations[char.slug])

        tasks = [asyncio.create_task(run_one(char)) for char in chars]
        reports: list[CharacterReport] = []
        for task in asyncio.as_completed(tasks):
            report = await task
            reports.append(report)
            sprite_count = sum(1 for f in report.files if not f.relative_path.startswith("conf/"))
            if report.error:
                console.print(f"[red]error:[/red] {report.character.slug}: {report.error}", highlight=False)
            else:
                mode = report.discovery_mode or "?"
                console.print(
                    f"[green]done:[/green] {report.character.slug}: {sprite_count} sprite(s), {mode}",
                    highlight=False,
                )
                for warning in report.warnings:
                    console.print(f"  [yellow]warning:[/yellow] {warning}", highlight=False)

        reports.sort(key=lambda r: r.character.slug)
        if args.json:
            payload = []
            for r in reports:
                payload.append(
                    {
                        "slug": r.character.slug,
                        "name": r.character.name,
                        "artist": r.character.artist,
                        "destination": str(r.destination),
                        "ok": r.ok,
                        "sprite_base": r.sprite_base,
                        "discovery_mode": r.discovery_mode,
                        "xml_images": r.xml_images,
                        "missing": r.missing,
                        "warnings": r.warnings,
                        "error": r.error,
                    }
                )
            print(json.dumps(payload, ensure_ascii=False, indent=2))

        failed = sum(1 for r in reports if not r.ok)
        console.print(
            f"[bold]Finished:[/bold] {len(reports) - failed}/{len(reports)} usable character(s). "
            f"Output: {output_root}",
            highlight=False,
        )
        return 1 if failed else 0


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        code = asyncio.run(async_main(args))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        code = 130
    except ShimejiDLError as exc:
        console.print(f"[red]error:[/red] {exc}", highlight=False)
        code = 2
    sys.exit(code)
