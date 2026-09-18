from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from .extractors.shimejis_xyz import ShimejisXYZExtractor
from .http import AsyncHTTP, Fetched
from .models import Character, CharacterReport, FileRecord
from .utils import encoded_asset_path, path_for_asset, sanitize_asset_path
from .xmltools import image_references, is_probable_config


def _looks_like_image(fetched: Fetched) -> bool:
    if not fetched.content:
        return False
    ctype = fetched.headers.get("content-type", "").lower()
    head = fetched.content[:64].lstrip().lower()
    if "text/html" in ctype or head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return False
    # PNG is overwhelmingly common. Other binary image types are accepted because
    # custom XML may reference them.
    signatures = (
        b"\x89PNG\r\n\x1a\n",
        b"\xff\xd8\xff",  # JPEG
        b"GIF87a",
        b"GIF89a",
        b"RIFF",  # WebP is checked below
    )
    if ctype.startswith("image/"):
        return True
    if fetched.content.startswith(signatures[:4]):
        return True
    return fetched.content.startswith(b"RIFF") and fetched.content[8:12] == b"WEBP"


class CharacterDownloader:
    def __init__(
        self,
        http: AsyncHTTP,
        extractor: ShimejisXYZExtractor,
        *,
        overwrite: bool = False,
        probe_max: int = 128,
        scan_extras: bool = False,
        no_config: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.http = http
        self.extractor = extractor
        self.overwrite = overwrite
        self.probe_max = max(1, probe_max)
        self.scan_extras = scan_extras
        self.no_config = no_config
        self.dry_run = dry_run

    async def download(self, char: Character, destination: Path) -> CharacterReport:
        report = CharacterReport(character=char, destination=destination, ok=False)
        try:
            char = await self.extractor.enrich(char)
            report.character = char
            image_base = await self._discover_image_base(char)
            if not image_base:
                report.error = "could not locate a sprite CDN"
                return report
            report.sprite_base = image_base

            if not self.dry_run:
                destination.mkdir(parents=True, exist_ok=True)

            root = image_base.rsplit("/img", 1)[0]
            actions = None
            behaviors = None

            if not self.no_config:
                actions, actions_url = await self._find_config(root, "actions")
                behaviors, behaviors_url = await self._find_config(root, "behaviors")
                report.actions_url = actions_url
                report.behaviors_url = behaviors_url

                if actions is not None and not self.dry_run:
                    saved = await self.http.save_bytes(
                        actions, destination / "conf" / "actions.xml", overwrite=self.overwrite
                    )
                    report.files.append(
                        FileRecord("conf/actions.xml", actions_url or "", saved.status, saved.size, saved.sha256)
                    )
                if behaviors is not None and not self.dry_run:
                    saved = await self.http.save_bytes(
                        behaviors, destination / "conf" / "behaviors.xml", overwrite=self.overwrite
                    )
                    report.files.append(
                        FileRecord(
                            "conf/behaviors.xml", behaviors_url or "", saved.status, saved.size, saved.sha256
                        )
                    )

                if (actions is None) != (behaviors is None):
                    report.warnings.append(
                        "only one custom XML config was exposed; VShimeji may fall back to its global "
                        "config for the other file"
                    )

            refs = image_references(actions) if actions else []
            report.xml_images = refs

            if refs:
                report.discovery_mode = "actions.xml"
                await self._download_named_images(image_base, destination, refs, report)
                if self.scan_extras:
                    await self._probe_numeric_images(image_base, destination, report, skip=set(refs))
            else:
                report.discovery_mode = "numeric-fallback"
                report.warnings.append(
                    "actions.xml unavailable or has no Image attributes; numeric shimeN.png probing was used"
                )
                await self._probe_numeric_images(image_base, destination, report, skip=set())

            image_records = [f for f in report.files if not f.relative_path.startswith("conf/")]
            report.ok = bool(image_records) and not report.missing
            if image_records and report.missing:
                # A partially recoverable character is still useful, but manifest it as partial.
                report.ok = True
                report.warnings.append(f"{len(report.missing)} referenced/probed image(s) could not be fetched")

            if not self.dry_run:
                self._write_manifest(report)
            return report
        except Exception as exc:  # keep pack downloads going if one item fails
            report.error = f"{type(exc).__name__}: {exc}"
            return report

    async def _discover_image_base(self, char: Character) -> str | None:
        candidates: list[str] = []
        if char.preview_url and "/img/" in char.preview_url:
            candidates.append(char.preview_url.split("/img/", 1)[0] + "/img")

        candidates.extend(
            [
                f"https://sprites.shimejis.xyz/directory/{char.slug}/img",
                f"https://sprite.shimejis.xyz/directory/{char.slug}/img",
            ]
        )

        # Preserve order while de-duplicating.
        ordered = list(dict.fromkeys(candidates))

        async def probe(base: str) -> tuple[str, bool]:
            # shime1.png is standard and is also used by VShimeji's chooser, but
            # old/custom packs can be imperfect. Probe a few initial indices so
            # discovery does not depend on exactly one filename.
            tests = await asyncio.gather(
                *(self.http.get(f"{base}/shime{i}.png", optional=True) for i in range(1, 6))
            )
            return base, any(item is not None and _looks_like_image(item) for item in tests)

        results = await asyncio.gather(*(probe(base) for base in ordered))
        for base, ok in results:
            if ok:
                return base
        return None

    async def _find_config(self, root: str, kind: str) -> tuple[bytes | None, str | None]:
        if kind == "actions":
            names = ["conf/actions.xml", "actions.xml", "conf/Actions.xml", "Actions.xml"]
        else:
            names = [
                "conf/behaviors.xml",
                "behaviors.xml",
                "conf/Behaviors.xml",
                "Behaviors.xml",
                "conf/Behavior.xml",
                "Behavior.xml",
            ]

        for name in names:
            url = f"{root.rstrip('/')}/{name}"
            fetched = await self.http.get(url, optional=True)
            if fetched and is_probable_config(fetched.content, kind):
                return fetched.content, fetched.final_url
        return None, None

    async def _download_named_images(
        self,
        image_base: str,
        destination: Path,
        refs: list[str],
        report: CharacterReport,
    ) -> None:
        async def one(raw: str) -> None:
            try:
                rel = sanitize_asset_path(raw)
            except ValueError:
                report.missing.append(raw)
                return
            url = f"{image_base.rstrip('/')}/{encoded_asset_path(rel)}"
            if self.dry_run:
                report.files.append(FileRecord(rel, url, "planned"))
                return
            target = path_for_asset(destination, rel)
            saved = await self.http.download(
                url,
                target,
                overwrite=self.overwrite,
                validator=_looks_like_image,
                optional=True,
            )
            if saved is None:
                report.missing.append(rel)
            else:
                report.files.append(FileRecord(rel, url, saved.status, saved.size, saved.sha256))

        await asyncio.gather(*(one(ref) for ref in refs))

    async def _probe_numeric_images(
        self,
        image_base: str,
        destination: Path,
        report: CharacterReport,
        *,
        skip: set[str],
    ) -> None:
        skip_folded = {x.casefold() for x in skip}

        async def one(index: int) -> None:
            rel = f"shime{index}.png"
            if rel.casefold() in skip_folded:
                return
            url = f"{image_base.rstrip('/')}/{rel}"
            if self.dry_run:
                report.files.append(FileRecord(rel, url, "probe-planned"))
                return
            target = destination / rel
            saved = await self.http.download(
                url,
                target,
                overwrite=self.overwrite,
                validator=_looks_like_image,
                optional=True,
            )
            if saved is not None:
                report.files.append(FileRecord(rel, url, saved.status, saved.size, saved.sha256))

        # Exhaustive inside the requested range: unlike a gap heuristic, holes do not
        # stop discovery and therefore shime90.png is still found if shime47..89 are absent.
        await asyncio.gather(*(one(i) for i in range(1, self.probe_max + 1)))

    @staticmethod
    def _write_manifest(report: CharacterReport) -> None:
        payload = {
            "schema_version": 1,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": asdict(report.character),
            "destination": str(report.destination),
            "ok": report.ok,
            "sprite_base": report.sprite_base,
            "discovery_mode": report.discovery_mode,
            "actions_url": report.actions_url,
            "behaviors_url": report.behaviors_url,
            "xml_images": report.xml_images,
            "files": [asdict(f) for f in report.files],
            "missing": report.missing,
            "warnings": report.warnings,
            "error": report.error,
        }
        path = report.destination / ".shimeji-dl.json"
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
