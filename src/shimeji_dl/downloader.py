from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .client import AsyncFetcher
from .models import CharacterRef, CharacterResult, ConfigResource, ImageRef, MissingAsset, ProbeReport
from .probe import numeric_sprite_indices, quiescence_span
from .utils import (
    atomic_write,
    atomic_write_json,
    collect_images,
    compress_numbers,
    is_valid_local_image,
    looks_like_image,
    natural_key,
    quote_asset_path,
)
from .xmlutil import extract_image_refs, is_valid_xml

ASSET_HOSTS = ("https://sprites.shimejis.xyz", "https://sprite.shimejis.xyz")
_PROBE_BATCH = 64


@dataclass(frozen=True, slots=True)
class DownloadOptions:
    output: Path
    jobs: int = 5
    probe_mode: str = "auto"
    force: bool = False
    metadata: bool = True
    strict: bool = False
    verbose: bool = False
    quiet: bool = False


class Downloader:
    def __init__(self, fetcher: AsyncFetcher, options: DownloadOptions) -> None:
        self.fetcher = fetcher
        self.options = options
        self._character_semaphore = asyncio.Semaphore(max(1, options.jobs))

    async def download_all(self, characters: list[CharacterRef]) -> list[CharacterResult]:
        self.options.output.mkdir(parents=True, exist_ok=True)
        tasks = [asyncio.create_task(self._limited_download(character)) for character in characters]
        return await asyncio.gather(*tasks)

    async def _limited_download(self, character: CharacterRef) -> CharacterResult:
        async with self._character_semaphore:
            return await self.download_character(character)

    async def download_character(self, character: CharacterRef) -> CharacterResult:
        self._log(f"download: {character.id}")
        dest = self.options.output / character.id
        conf_dir = dest / "conf"
        dest.mkdir(parents=True, exist_ok=True)

        roots = [f"{host}/directory/{character.id}" for host in ASSET_HOSTS]
        actions_task = asyncio.create_task(self._get_config("actions.xml", roots, conf_dir))
        behaviors_task = asyncio.create_task(self._get_config("behaviors.xml", roots, conf_dir))
        actions, behaviors = await asyncio.gather(actions_task, behaviors_task)

        refs = _merge_refs(actions.image_refs if actions else [], behaviors.image_refs if behaviors else [])
        roots = _prioritize_roots(roots, actions, behaviors)

        referenced_missing: list[MissingAsset] = []
        referenced_present: set[str] = set()
        if refs:
            asset_results = await asyncio.gather(*(self._download_ref(ref, roots, dest) for ref in refs))
            for ref, success, tried_urls in asset_results:
                if success:
                    referenced_present.add(ref.path)
                else:
                    referenced_missing.append(
                        MissingAsset(path=ref.path, kind="referenced-missing", tried_urls=tuple(tried_urls))
                    )

        probe = await self._adaptive_numeric_probe(
            roots=roots,
            dest=dest,
            xml_paths={ref.path for ref in refs},
            referenced_present=referenced_present,
        )

        sprite_paths = collect_images(dest)
        if refs and probe.mode != "off":
            discovery = "xml+adaptive-probe"
        elif refs:
            discovery = "xml-references"
        elif probe.hits:
            discovery = "adaptive-probe"
        else:
            discovery = "none"
        usable = bool(sprite_paths)

        result = CharacterResult(
            character=character,
            output_dir=str(dest),
            sprite_paths=sprite_paths,
            discovery=discovery,
            actions=actions,
            behaviors=behaviors,
            referenced_missing=referenced_missing,
            probe=probe,
            usable=usable,
        )

        if self.options.metadata:
            await asyncio.to_thread(self._write_metadata, dest, result)

        self._print_result(result)
        return result

    async def _get_config(self, name: str, roots: list[str], conf_dir: Path) -> ConfigResource | None:
        local_path = conf_dir / name
        if local_path.exists() and not self.options.force:
            try:
                data = await asyncio.to_thread(local_path.read_bytes)
            except OSError:
                data = b""
            if data and is_valid_xml(data):
                return ConfigResource(
                    name=name,
                    data=data,
                    source_url=None,
                    cached=True,
                    image_refs=extract_image_refs(data),
                )

        # BYO packages place XML beside img/. Some mirrors use conf/.
        candidates = [f"{root}/{name}" for root in roots] + [f"{root}/conf/{name}" for root in roots]
        responses = await asyncio.gather(*(self.fetcher.get(url, optional=True) for url in candidates))
        for requested_url, response in zip(candidates, responses, strict=True):
            if response is None or not is_valid_xml(response.content):
                continue
            await asyncio.to_thread(atomic_write, local_path, response.content)
            return ConfigResource(
                name=name,
                data=response.content,
                source_url=response.url or requested_url,
                cached=False,
                image_refs=extract_image_refs(response.content),
            )
        return None

    async def _download_ref(
        self,
        ref: ImageRef,
        roots: list[str],
        dest: Path,
    ) -> tuple[ImageRef, bool, list[str]]:
        local_path = dest.joinpath(*ref.path.split("/"))
        if local_path.exists() and not self.options.force:
            valid = await asyncio.to_thread(is_valid_local_image, local_path)
            if valid:
                return ref, True, []

        urls = [ref.absolute_url] if ref.absolute_url else [
            f"{root}/img/{quote_asset_path(ref.path)}" for root in roots
        ]
        tried: list[str] = []
        for url in urls:
            if not url:
                continue
            tried.append(url)
            response = await self.fetcher.get(url, optional=True)
            if response is None or not looks_like_image(response.content, ref.path, response.content_type):
                continue
            await asyncio.to_thread(atomic_write, local_path, response.content)
            return ref, True, tried
        return ref, False, tried

    async def _adaptive_numeric_probe(
        self,
        *,
        roots: list[str],
        dest: Path,
        xml_paths: set[str],
        referenced_present: set[str],
    ) -> ProbeReport:
        mode = self.options.probe_mode
        report = ProbeReport(mode=mode)
        if mode == "off":
            return report

        xml_anchors = numeric_sprite_indices(xml_paths)
        existing_paths = collect_images(dest)
        existing_hits = numeric_sprite_indices(existing_paths)
        referenced_hits = numeric_sprite_indices(referenced_present)
        hits: set[int] = set(existing_hits | referenced_hits)
        misses: set[int] = set()
        extra_hits: set[str] = set()
        report.xml_anchors = sorted(xml_anchors)

        async def probe_one(index: int, phase: str) -> bool:
            if index <= 0:
                return False
            if index in hits:
                return True
            if index in misses:
                return False

            path = f"shime{index}.png"
            report.requests += 1
            if phase == "gallop":
                report.gallop_probes += 1
            elif phase == "bisect":
                report.bisect_probes += 1
            elif phase == "fill":
                report.fill_probes += 1
            elif phase == "quiescence":
                report.quiescence_probes += 1

            _, _, hit = await self._probe_numeric(index, roots, dest, referenced_present)
            if hit:
                hits.add(index)
                if path not in xml_paths:
                    extra_hits.add(path)
                return True
            misses.add(index)
            return False

        async def probe_range(start: int, end: int, phase: str) -> bool:
            """Probe a closed range in bounded async batches.

            Returns True if this call discovers a hit that was not known before.
            """
            if end < start:
                return False
            before = set(hits)
            cursor = start
            while cursor <= end:
                batch_end = min(end, cursor + _PROBE_BATCH - 1)
                await asyncio.gather(*(probe_one(index, phase) for index in range(cursor, batch_end + 1)))
                cursor = batch_end + 1
            return bool(hits - before)

        # No XML/local numeric anchor: establish a small seed area. This is not
        # an index ceiling; once any hit exists, the search grows adaptively.
        if not hits:
            seed_span = 32 if mode == "deep" else 8
            await probe_range(1, seed_span, "fill")
            if not hits:
                report.hits = []
                report.extra_hits = []
                report.misses = sorted(misses)
                report.highest_tested = max(misses, default=None)
                report.stop_reason = "no-numeric-seed"
                return report

        # Fill every numeric hole up to a real known hit. XML anchors make this
        # exact for the useful namespace already demonstrated by the pack.
        await probe_range(1, max(hits), "fill")

        while hits:
            frontier = max(hits)
            span_hint = 0

            # Gallop: +1, +2, +4, +8 ... while matching. This rapidly brackets
            # the end of a dense sequence without imposing any shimeN ceiling.
            offset = 1
            last_hit = frontier
            first_miss: int | None = None
            while True:
                candidate = frontier + offset
                if await probe_one(candidate, "gallop"):
                    last_hit = candidate
                    offset *= 2
                    continue
                first_miss = candidate
                span_hint = candidate - frontier
                break

            # First failure brackets the dense frontier. Bisect the hit/miss
            # interval, then fill all candidates up to the resulting boundary.
            # If the pack has holes, the later quiescence phase still searches
            # beyond that provisional boundary and can re-open exploration.
            if last_hit > frontier and first_miss is not None:
                low = last_hit
                high = first_miss
                while high - low > 1:
                    middle = (low + high) // 2
                    if await probe_one(middle, "bisect"):
                        low = middle
                    else:
                        high = middle
                await probe_range(frontier + 1, low, "fill")
                frontier = max(hits)

            # Absence is never inferred from one 404. Search a quiet tail whose
            # length comes from the pack's observed sparsity and gallop span.
            quiet = quiescence_span(hits, mode, span_hint=span_hint)
            report.quiescence_span = max(report.quiescence_span, quiet)
            quiet_end = frontier + quiet
            found_beyond_frontier = False

            cursor = frontier + 1
            while cursor <= quiet_end:
                batch_end = min(quiet_end, cursor + _PROBE_BATCH - 1)
                before_highest = max(hits)
                await asyncio.gather(*(probe_one(index, "quiescence") for index in range(cursor, batch_end + 1)))
                if max(hits) > before_highest:
                    found_beyond_frontier = True
                    break
                cursor = batch_end + 1

            if found_beyond_frontier:
                # New evidence extends the namespace. Recompute its shape and
                # gallop again from the newly discovered highest hit.
                continue

            report.stop_reason = "quiescent-tail"
            break

        report.hits = sorted(hits)
        report.extra_hits = sorted(extra_hits, key=natural_key)
        report.misses = sorted(misses)
        report.highest_hit = max(hits, default=None)
        report.highest_tested = max(hits | misses, default=None)
        return report

    async def _probe_numeric(
        self,
        index: int,
        roots: list[str],
        dest: Path,
        known: set[str],
    ) -> tuple[int, str, bool]:
        path = f"shime{index}.png"
        local_path = dest / path
        if path in known:
            return index, path, True
        if local_path.exists() and not self.options.force:
            valid = await asyncio.to_thread(is_valid_local_image, local_path)
            if valid:
                return index, path, True

        for root in roots:
            url = f"{root}/img/{path}"
            response = await self.fetcher.get(url, optional=True)
            if response is None or not looks_like_image(response.content, path, response.content_type):
                continue
            await asyncio.to_thread(atomic_write, local_path, response.content)
            return index, path, True
        return index, path, False

    def _write_metadata(self, dest: Path, result: CharacterResult) -> None:
        actions = _config_metadata(result.actions)
        behaviors = _config_metadata(result.behaviors)
        metadata = {
            "schema_version": 2,
            "tool": {"name": "shimeji-dl", "version": __version__},
            "extractor": result.character.extractor,
            "id": result.character.id,
            "source": result.character.source_url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "usable": result.usable,
            "completeness": _completeness(result),
            "discovery": {
                "mode": result.discovery,
                "xml_referenced": sorted(
                    {ref.path for config in (result.actions, result.behaviors) if config for ref in config.image_refs},
                    key=natural_key,
                ),
                "probe": {
                    "mode": result.probe.mode,
                    "strategy": "gallop-bisect-adaptive-quiescence",
                    "xml_anchors": result.probe.xml_anchors,
                    "hits": result.probe.hits,
                    "extra_hits": result.probe.extra_hits,
                    "tested_count": result.probe.requests,
                    "gallop_probes": result.probe.gallop_probes,
                    "bisect_probes": result.probe.bisect_probes,
                    "fill_probes": result.probe.fill_probes,
                    "quiescence_probes": result.probe.quiescence_probes,
                    "quiescence_span": result.probe.quiescence_span,
                    "highest_hit": result.probe.highest_hit,
                    "highest_tested": result.probe.highest_tested,
                    "missing_count": len(result.probe.misses),
                    "missing_ranges": compress_numbers(result.probe.misses),
                    "stop_reason": result.probe.stop_reason,
                },
            },
            "config": {
                "actions": actions,
                "behaviors": behaviors,
                "behavior_runtime": "custom" if result.behaviors else "VShimeji global fallback",
            },
            "sprites": {
                "count": len(result.sprite_paths),
                "files": result.sprite_paths,
                "probe_only": result.probe.extra_hits,
                "referenced_missing": [
                    {
                        "path": item.path,
                        "kind": item.kind,
                        "tried_urls": list(item.tried_urls),
                    }
                    for item in result.referenced_missing
                ],
            },
        }
        atomic_write_json(dest / "metadata.json", metadata)

    def _print_result(self, result: CharacterResult) -> None:
        if self.options.quiet:
            return
        parts = [f"{len(result.sprite_paths)} sprite(s)"]
        parts.append("actions.xml" if result.actions else "no-actions.xml")
        parts.append("behaviors.xml" if result.behaviors else "default-behaviors")
        if result.probe.mode != "off":
            parts.append(f"probe:{result.probe.mode}")
        print(f"done: {result.character.id}: {', '.join(parts)}", flush=True)

        for missing in result.referenced_missing:
            print(f"  warning: referenced-missing: {missing.path}", flush=True)
            if self.options.verbose:
                for url in missing.tried_urls:
                    print(f"    tried: {url}", flush=True)

        if not result.actions or not result.actions.image_refs:
            print(
                "  warning: actions.xml unavailable or has no image references; "
                "adaptive numeric probing was used"
                if result.probe.mode != "off"
                else "  warning: actions.xml unavailable or has no image references",
                flush=True,
            )
        if not result.behaviors:
            self._log("  info: behaviors.xml unavailable; VShimeji will use its global behaviors.xml")
        if self.options.verbose and result.probe.mode != "off":
            print(
                f"  probe: hits={len(result.probe.hits)}, extras={len(result.probe.extra_hits)}, "
                f"tested={result.probe.requests}, highest={result.probe.highest_tested}, "
                f"stop={result.probe.stop_reason}",
                flush=True,
            )
            if result.probe.misses:
                print("  probe-missing: " + ", ".join(compress_numbers(result.probe.misses)), flush=True)

    def _log(self, message: str) -> None:
        if not self.options.quiet:
            print(message, flush=True)


def _merge_refs(*groups: list[ImageRef]) -> list[ImageRef]:
    merged: list[ImageRef] = []
    seen: set[tuple[str, str | None]] = set()
    for group in groups:
        for ref in group:
            key = (ref.path, ref.absolute_url)
            if key in seen:
                continue
            seen.add(key)
            merged.append(ref)
    return merged


def _prioritize_roots(
    roots: list[str],
    actions: ConfigResource | None,
    behaviors: ConfigResource | None,
) -> list[str]:
    preferred: list[str] = []
    for config in (actions, behaviors):
        if not config or not config.source_url:
            continue
        source = urlsplit(config.source_url)
        origin = f"{source.scheme}://{source.netloc}"
        for root in roots:
            if root.startswith(origin) and root not in preferred:
                preferred.append(root)
    preferred.extend(root for root in roots if root not in preferred)
    return preferred


def _config_metadata(config: ConfigResource | None) -> dict[str, object]:
    if config is None:
        return {"available": False, "source_url": None, "cached": False, "image_references": []}
    return {
        "available": True,
        "source_url": config.source_url,
        "cached": config.cached,
        "image_references": [ref.path for ref in config.image_refs],
    }


def _completeness(result: CharacterResult) -> str:
    if result.referenced_missing:
        return "incomplete"
    if (result.actions and result.actions.image_refs) or (result.behaviors and result.behaviors.image_refs):
        return "referenced-complete"
    if result.usable and result.discovery == "adaptive-probe":
        return "best-effort"
    return "unknown"
