from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..version import get_version
from .http import HttpClient
from .interfaces import ConfigFormat, Reporter, SourceAdapter
from .models import (
    AssetRef,
    CharacterRef,
    CharacterResult,
    ConfigResource,
    MissingAsset,
    ProbeReport,
)
from .probing import AdaptiveNumericProber, numeric_indices
from .storage import (
    atomic_write,
    atomic_write_json,
    collect_images,
    collect_sounds,
    compress_numbers,
    is_valid_local_resource,
    looks_like_resource,
    natural_key,
)


@dataclass(frozen=True, slots=True)
class DownloadOptions:
    output: Path
    jobs: int = 5
    probe_mode: str = "auto"
    overwrite: bool = False
    metadata: bool = True
    strict: bool = False


class DownloadEngine:
    def __init__(
        self,
        client: HttpClient,
        options: DownloadOptions,
        *,
        sources: dict[str, SourceAdapter],
        config_format: ConfigFormat,
        reporter: Reporter,
    ) -> None:
        self.client = client
        self.options = options
        self.sources = sources
        self.config_format = config_format
        self.reporter = reporter
        self._character_semaphore = asyncio.Semaphore(max(1, options.jobs))

    async def download_all(self, characters: list[CharacterRef]) -> list[CharacterResult]:
        self.options.output.mkdir(parents=True, exist_ok=True)
        self.reporter.start(characters)
        try:
            return await asyncio.gather(*(self._limited_download(character) for character in characters))
        finally:
            self.reporter.finish()

    async def _limited_download(self, character: CharacterRef) -> CharacterResult:
        async with self._character_semaphore:
            try:
                return await self.download_character(character)
            except Exception as exc:
                result = CharacterResult(
                    character=character,
                    output_dir=str(self.options.output / character.id),
                    asset_paths=collect_images(self.options.output / character.id),
                    discovery="error",
                    configs={},
                    referenced_missing=[],
                    probe=ProbeReport(mode=self.options.probe_mode, stop_reason="error"),
                    usable=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
                self.reporter.character_finished(result)
                return result

    async def download_character(self, character: CharacterRef) -> CharacterResult:
        source = self.sources[character.source]
        self.reporter.character_started(character)
        dest = self.options.output / character.id
        conf_dir = dest / "conf"
        dest.mkdir(parents=True, exist_ok=True)

        self.reporter.character_phase(character, "Config")
        config_items = await asyncio.gather(
            *(self._get_config(source, character, name, conf_dir) for name in source.config_names)
        )
        configs = dict(zip(source.config_names, config_items, strict=True))
        source.prioritize(character, config_items)

        refs = _merge_refs(*(config.asset_refs for config in config_items if config))
        referenced_missing: list[MissingAsset] = []
        referenced_present: set[str] = set()

        if refs:
            self.reporter.character_phase(character, "XML assets", f"{len(refs)} referenced")
            results = await asyncio.gather(*(self._download_ref(source, character, ref, dest) for ref in refs))
            for ref, success, tried_urls in results:
                if success:
                    referenced_present.add(ref.path)
                else:
                    referenced_missing.append(MissingAsset(ref.path, "referenced-missing", tuple(tried_urls)))

        self.reporter.character_phase(character, "Adaptive probe")
        probe = await self._probe(source, character, dest, {ref.path for ref in refs}, referenced_present)

        asset_paths = collect_images(dest)
        referenced_paths = {ref.path for ref in refs}
        probe.extra_hits = sorted(
            {f"shime{index}.png" for index in probe.hits if f"shime{index}.png" not in referenced_paths},
            key=natural_key,
        )
        if refs and probe.mode != "off":
            discovery = "xml+adaptive-probe"
        elif refs:
            discovery = "xml-references"
        elif probe.hits:
            discovery = "adaptive-probe"
        else:
            discovery = "none"

        result = CharacterResult(
            character=character,
            output_dir=str(dest),
            asset_paths=asset_paths,
            discovery=discovery,
            configs=configs,
            referenced_missing=referenced_missing,
            probe=probe,
            usable=bool(asset_paths),
        )

        if self.options.metadata:
            await asyncio.to_thread(self._write_metadata, dest, result)
        self.reporter.character_finished(result)
        return result

    async def _get_config(
        self,
        source: SourceAdapter,
        character: CharacterRef,
        name: str,
        conf_dir: Path,
    ) -> ConfigResource | None:
        local_path = conf_dir / name
        if local_path.exists() and not self.options.overwrite:
            try:
                data = await asyncio.to_thread(local_path.read_bytes)
            except OSError:
                data = b""
            if data and self.config_format.is_valid(data):
                return ConfigResource(name, data, None, True, self.config_format.extract_asset_refs(data))

        for url in source.config_candidates(character, name):
            response = await self.client.get(url, optional=True, headers=source.request_headers())
            if response is None or not self.config_format.is_valid(response.content):
                continue
            await asyncio.to_thread(atomic_write, local_path, response.content)
            return ConfigResource(
                name,
                response.content,
                response.url,
                False,
                self.config_format.extract_asset_refs(response.content),
            )
        return None

    async def _download_ref(
        self,
        source: SourceAdapter,
        character: CharacterRef,
        ref: AssetRef,
        dest: Path,
    ) -> tuple[AssetRef, bool, list[str]]:
        local_path = dest.joinpath(*ref.path.split("/"))
        if (
            local_path.exists()
            and not self.options.overwrite
            and await asyncio.to_thread(is_valid_local_resource, local_path)
        ):
            return ref, True, []

        tried: list[str] = []
        for url in source.asset_candidates(character, ref):
            tried.append(url)
            response = await self.client.get(url, optional=True, headers=source.request_headers())
            if response is None or not looks_like_resource(response.content, ref.path, response.content_type):
                continue
            await asyncio.to_thread(atomic_write, local_path, response.content)
            return ref, True, tried
        return ref, False, tried

    async def _probe(
        self,
        source: SourceAdapter,
        character: CharacterRef,
        dest: Path,
        xml_paths: set[str],
        referenced_present: set[str],
    ) -> ProbeReport:
        anchors = numeric_indices(xml_paths)
        known = numeric_indices(collect_images(dest)) | numeric_indices(referenced_present)

        async def probe_index(index: int) -> bool:
            ref = source.numeric_asset(character, index)
            _, success, _ = await self._download_ref(source, character, ref, dest)
            return success

        return await AdaptiveNumericProber(mode=self.options.probe_mode).run(
            probe_index,
            anchors=anchors,
            known_hits=known,
        )

    def _write_metadata(self, dest: Path, result: CharacterResult) -> None:
        sounds = collect_sounds(dest)
        referenced = sorted(
            {ref.path for config in result.configs.values() if config for ref in config.asset_refs},
            key=natural_key,
        )
        metadata = {
            "schema_version": 5,
            "tool": {"name": "shimeji-dl", "version": get_version()},
            "source_adapter": result.character.source,
            "id": result.character.id,
            "source": result.character.source_url,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
            "usable": result.usable,
            "complete": result.complete,
            "error": result.error,
            "completeness": _completeness(result),
            "discovery": {
                "mode": result.discovery,
                "xml_referenced": referenced,
                "probe": {
                    "mode": result.probe.mode,
                    "strategy": "gallop-bisect-adaptive-quiescence",
                    "anchors": result.probe.anchors,
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
            "config": {name: _config_metadata(config) for name, config in result.configs.items()},
            "assets": {
                "count": len(result.asset_paths),
                "files": result.asset_paths,
                "probe_only": result.probe.extra_hits,
                "sound_count": len(sounds),
                "sounds": sounds,
                "referenced_missing": [
                    {"path": item.path, "kind": item.kind, "tried_urls": list(item.tried_urls)}
                    for item in result.referenced_missing
                ],
            },
        }
        atomic_write_json(dest / "metadata.json", metadata)


def _merge_refs(*groups: list[AssetRef]) -> list[AssetRef]:
    merged: list[AssetRef] = []
    seen: set[tuple[str, str | None]] = set()
    for group in groups:
        for ref in group:
            key = (ref.path, ref.absolute_url)
            if key not in seen:
                seen.add(key)
                merged.append(ref)
    return merged


def _config_metadata(config: ConfigResource | None) -> dict[str, object]:
    if config is None:
        return {"available": False, "source_url": None, "cached": False, "asset_references": []}
    return {
        "available": True,
        "source_url": config.source_url,
        "cached": config.cached,
        "asset_references": [ref.path for ref in config.asset_refs],
    }


def _completeness(result: CharacterResult) -> str:
    if result.error:
        return "error"
    if result.referenced_missing:
        return "incomplete"
    if any(config and config.asset_refs for config in result.configs.values()):
        return "referenced-complete"
    if result.usable and result.discovery == "adaptive-probe":
        return "best-effort"
    return "unknown"
