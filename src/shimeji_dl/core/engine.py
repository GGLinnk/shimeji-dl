from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from ..version import get_version
from .http import HttpClient
from .interfaces import ConfigFormat, ManifestSourceAdapter, Reporter, SourceAdapter
from .models import (
    AssetRef,
    CharacterRef,
    CharacterResult,
    ConfigResource,
    MissingAsset,
    ProbeReport,
    SourceManifest,
    SpriteRegion,
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

        self.reporter.character_phase(character, "Manifest")
        manifest = await self._get_manifest(source, character)

        self.reporter.character_phase(character, "Config")
        config_items = await asyncio.gather(
            *(
                self._get_config(source, character, name, conf_dir, manifest)
                for name in source.config_names
            )
        )
        configs = dict(zip(source.config_names, config_items, strict=True))
        source.prioritize(character, config_items)

        config_refs = _merge_refs(*(config.asset_refs for config in config_items if config))
        refs = _merge_refs(config_refs, manifest.asset_refs if manifest else [])
        referenced_missing: list[MissingAsset] = []
        referenced_present: set[str] = set()
        atlas_paths: set[str] = set()

        if manifest and manifest.sprites:
            self.reporter.character_phase(character, "Sprite atlas", f"{len(manifest.sprites)} listed")
            atlas_paths = await self._materialize_spritesheet(source, manifest, dest)
            referenced_present.update(atlas_paths)

        if refs:
            self.reporter.character_phase(character, "XML assets", f"{len(refs)} referenced")
            pending = [ref for ref in refs if ref.path not in atlas_paths]
            results = await asyncio.gather(
                *(self._download_ref(source, character, ref, dest) for ref in pending)
            )
            for ref, success, tried_urls in results:
                if success:
                    referenced_present.add(ref.path)
                else:
                    kind = (
                        "source-missing"
                        if manifest is not None
                        and manifest.authoritative
                        and ref.path not in manifest.sprites
                        else "referenced-missing"
                    )
                    referenced_missing.append(MissingAsset(ref.path, kind, tuple(tried_urls)))

        manifest_is_complete = (
            manifest is not None
            and manifest.authoritative
            and self.options.probe_mode != "deep"
        )
        if (
            manifest is None
            or not manifest.authoritative
            or self.options.probe_mode == "deep"
        ):
            self.reporter.character_phase(character, "Adaptive probe")
            probe = await self._probe(
                source,
                character,
                dest,
                {ref.path for ref in refs},
                referenced_present,
            )
        else:
            probe = _manifest_probe(self.options.probe_mode, config_refs, manifest)

        asset_paths = collect_images(dest)
        referenced_paths = {ref.path for ref in config_refs}
        probe.extra_hits = sorted(
            {f"shime{index}.png" for index in probe.hits if f"shime{index}.png" not in referenced_paths},
            key=natural_key,
        )
        if manifest_is_complete:
            discovery = "xml+source-manifest" if config_refs else "source-manifest"
        elif manifest is not None and config_refs and probe.mode != "off":
            discovery = "xml+source-manifest+adaptive-probe"
        elif manifest is not None:
            discovery = "source-manifest+adaptive-probe" if probe.mode != "off" else "source-manifest"
        elif refs and probe.mode != "off":
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
            manifest=manifest,
            atlas_paths=sorted(atlas_paths, key=natural_key),
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
        manifest: SourceManifest | None,
    ) -> ConfigResource | None:
        local_path = conf_dir / name
        if local_path.exists() and not self.options.overwrite:
            try:
                data = await asyncio.to_thread(local_path.read_bytes)
            except OSError:
                data = b""
            if data and self.config_format.is_valid(data):
                return ConfigResource(name, data, None, True, self.config_format.extract_asset_refs(data))

        manifest_data = manifest.configs.get(name) if manifest else None
        if manifest_data and self.config_format.is_valid(manifest_data):
            await asyncio.to_thread(atomic_write, local_path, manifest_data)
            return ConfigResource(
                name,
                manifest_data,
                manifest.source_url if manifest else None,
                False,
                self.config_format.extract_asset_refs(manifest_data),
            )

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

    async def _get_manifest(
        self,
        source: SourceAdapter,
        character: CharacterRef,
    ) -> SourceManifest | None:
        if not isinstance(source, ManifestSourceAdapter):
            return None
        return await source.fetch_manifest(self.client, character)

    async def _materialize_spritesheet(
        self,
        source: SourceAdapter,
        manifest: SourceManifest,
        dest: Path,
    ) -> set[str]:
        present = (
            set()
            if self.options.overwrite
            else await asyncio.to_thread(_valid_manifest_paths, manifest, dest)
        )
        needed = {path: region for path, region in manifest.sprites.items() if path not in present}
        if not needed or not manifest.spritesheet_url:
            return present

        response = await self.client.get(
            manifest.spritesheet_url,
            optional=True,
            headers=source.request_headers(),
        )
        if response is None or not looks_like_resource(
            response.content,
            "spritesheet.png",
            response.content_type,
        ):
            return present

        extracted = await asyncio.to_thread(
            _extract_sprite_regions,
            response.content,
            needed,
            dest,
        )
        return present | extracted

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
            "schema_version": 6,
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
                "source_manifest": _manifest_metadata(result),
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
        if all(item.kind == "source-missing" for item in result.referenced_missing):
            return "source-missing"
        return "incomplete"
    if any(config and config.asset_refs for config in result.configs.values()):
        return "referenced-complete"
    if result.usable and result.discovery == "adaptive-probe":
        return "best-effort"
    return "unknown"


def _manifest_probe(mode: str, config_refs: list[AssetRef], manifest: SourceManifest) -> ProbeReport:
    anchors = sorted(numeric_indices({ref.path for ref in config_refs}))
    hits = sorted(numeric_indices(set(manifest.sprites)))
    return ProbeReport(
        mode=mode,
        anchors=anchors,
        hits=hits,
        requests=0,
        highest_hit=max(hits, default=None),
        highest_tested=max(hits, default=None),
        stop_reason="source-manifest",
    )


def _extract_sprite_regions(
    spritesheet: bytes,
    regions: dict[str, SpriteRegion],
    dest: Path,
) -> set[str]:
    extracted: set[str] = set()
    try:
        with Image.open(BytesIO(spritesheet)) as image:
            image.load()
            sheet_width, sheet_height = image.size
            for path, region in regions.items():
                right = region.x + region.width
                bottom = region.y + region.height
                if right > sheet_width or bottom > sheet_height:
                    continue
                sprite = image.crop((region.x, region.y, right, bottom))
                output = BytesIO()
                sprite.save(output, format="PNG", optimize=False)
                atomic_write(dest.joinpath(*path.split("/")), output.getvalue())
                extracted.add(path)
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
        return set()
    return extracted


def _valid_manifest_paths(manifest: SourceManifest, dest: Path) -> set[str]:
    return {
        path
        for path in manifest.sprites
        if is_valid_local_resource(dest.joinpath(*path.split("/")))
    }


def _manifest_metadata(result: CharacterResult) -> dict[str, object]:
    manifest = result.manifest
    if manifest is None:
        return {"available": False}
    return {
        "available": True,
        "authoritative": manifest.authoritative,
        "source_url": manifest.source_url,
        "spritesheet_url": manifest.spritesheet_url,
        "sprite_count": len(manifest.sprites),
        "materialized_count": len(result.atlas_paths),
        "metadata": manifest.metadata,
    }
