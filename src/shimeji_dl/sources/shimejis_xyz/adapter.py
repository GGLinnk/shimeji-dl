from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

from lxml import html

from ...core.http import HttpClient
from ...core.models import (
    AssetRef,
    CharacterRef,
    ConfigResource,
    SourceManifest,
    SpriteRegion,
)
from ...core.storage import normalize_asset_ref, quote_asset_path

SITE = "https://shimejis.xyz"
DIRECTORY = f"{SITE}/directory"
CHARACTER_PREFIX = "/directory/shimeji/"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ASSET_HOSTS = ("https://sprites.shimejis.xyz", "https://sprite.shimejis.xyz")
WHOLE_SITE_TARGETS = {"shimejis.xyz", "www.shimejis.xyz"}


class ShimejisXYZSource:
    key = "shimejis.xyz"
    config_names = ("actions.xml", "behaviors.xml", "info.xml")

    def __init__(self) -> None:
        self._preferred_hosts: dict[str, tuple[str, ...]] = {}

    @classmethod
    def suitable(cls, target: str) -> bool:
        normalized = target.strip().lower().rstrip("/")
        if normalized in WHOLE_SITE_TARGETS:
            return True
        if "://" not in normalized:
            return bool(SLUG_RE.fullmatch(normalized))
        parsed = urlsplit(normalized)
        return parsed.scheme in {"http", "https"} and parsed.hostname in WHOLE_SITE_TARGETS

    def confirmation_message(self, target: str) -> str | None:
        if _is_whole_site_target(target):
            return "This target covers the entire shimejis.xyz directory and may download many characters. Continue?"
        return None

    async def extract(self, client: HttpClient, target: str) -> list[CharacterRef]:
        normalized = target.strip()
        if _is_whole_site_target(normalized):
            return await self._extract_site(client)

        if "://" not in normalized:
            slug = normalized.lower()
            if slug.endswith("-shimeji-pack"):
                return await self._extract_pack(client, f"{SITE}/directory/{slug}")
            return [self._character(slug)]

        parsed = urlsplit(normalized)
        path = parsed.path.rstrip("/")
        if path.startswith(CHARACTER_PREFIX):
            slug = path[len(CHARACTER_PREFIX):]
            if not SLUG_RE.fullmatch(slug):
                raise ValueError(f"invalid shimeji slug in URL: {target}")
            return [self._character(slug)]
        if path.startswith("/directory/") and path.count("/") == 2:
            return await self._extract_pack(client, f"{SITE}{path}")
        raise ValueError(f"unsupported shimejis.xyz URL: {target}")

    async def fetch_manifest(self, client: HttpClient, character: CharacterRef) -> SourceManifest | None:
        url = f"{SITE}/api/shimeji/{character.id}/configuration"
        response = await client.get(url, optional=True, headers=self.request_headers())
        if response is None:
            return None

        try:
            payload = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        if not isinstance(payload, dict):
            return None

        configs = {
            filename: value.encode("utf-8")
            for filename in self.config_names
            if isinstance((value := payload.get(filename.removesuffix(".xml"))), str)
        }
        sprites = _parse_sprites(payload.get("sprites"))
        spritesheet_url = _asset_url(payload.get("spritesheet"))
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        if spritesheet_url:
            origin = _origin(spritesheet_url)
            if origin in ASSET_HOSTS:
                self._preferred_hosts[character.id] = (origin,) + tuple(
                    host for host in ASSET_HOSTS if host != origin
                )

        if not configs and not sprites:
            return None
        return SourceManifest(
            source_url=response.url,
            authoritative=True,
            configs=configs,
            spritesheet_url=spritesheet_url,
            sprites=sprites,
            metadata=metadata,
        )

    def request_headers(self) -> dict[str, str]:
        return {"Referer": f"{SITE}/"}

    def config_candidates(self, character: CharacterRef, name: str) -> list[str]:
        return [f"{root}/{name}" for root in self._roots(character)] + [
            f"{root}/conf/{name}" for root in self._roots(character)
        ]

    def asset_candidates(self, character: CharacterRef, ref: AssetRef) -> list[str]:
        if ref.absolute_url:
            return [ref.absolute_url]

        roots = self._roots(character)
        if ref.path.lower().startswith("sound/"):
            quoted = quote_asset_path(ref.path[len("sound/"):])
            return [
                candidate
                for root in roots
                for candidate in (f"{root}/sound/{quoted}", f"{root}/img/sound/{quoted}")
            ]

        quoted = quote_asset_path(ref.path)
        return [f"{root}/img/{quoted}" for root in roots]

    def numeric_asset(self, character: CharacterRef, index: int) -> AssetRef:
        path = f"shime{index}.png"
        return AssetRef(value=path, path=path)

    def prioritize(self, character: CharacterRef, configs: Iterable[ConfigResource | None]) -> None:
        preferred: list[str] = []
        for config in configs:
            if not config or not config.source_url:
                continue
            origin = _origin(config.source_url)
            if origin in ASSET_HOSTS and origin not in preferred:
                preferred.append(origin)
        preferred.extend(host for host in ASSET_HOSTS if host not in preferred)
        self._preferred_hosts[character.id] = tuple(preferred)

    async def _extract_site(self, client: HttpClient) -> list[CharacterRef]:
        page = await client.get_text(DIRECTORY, headers=self.request_headers())
        packs = extract_pack_urls_from_html(page)
        if not packs:
            raise ValueError(f"no packs found in directory: {DIRECTORY}")
        groups = await asyncio.gather(*(self._extract_pack(client, url) for url in packs))
        return _unique_characters(character for group in groups for character in group)

    async def _extract_pack(self, client: HttpClient, url: str) -> list[CharacterRef]:
        page = await client.get_text(url, headers=self.request_headers())
        slugs = extract_slugs_from_html(page)
        if not slugs:
            raise ValueError(f"no character links found in pack: {url}")
        return [self._character(slug) for slug in slugs]

    def _roots(self, character: CharacterRef) -> list[str]:
        hosts = self._preferred_hosts.get(character.id, ASSET_HOSTS)
        return [f"{host}/directory/{character.id}" for host in hosts]

    @staticmethod
    def _character(slug: str) -> CharacterRef:
        return CharacterRef(
            source=ShimejisXYZSource.key,
            id=slug,
            source_url=f"{SITE}{CHARACTER_PREFIX}{slug}",
        )


def extract_slugs_from_html(document: str) -> list[str]:
    tree = html.fromstring(document)
    slugs: list[str] = []
    seen: set[str] = set()
    for href in tree.xpath("//a/@href"):
        path = urlsplit(urljoin(SITE, str(href))).path.rstrip("/")
        if not path.startswith(CHARACTER_PREFIX):
            continue
        slug = path[len(CHARACTER_PREFIX):]
        if "/" in slug or not SLUG_RE.fullmatch(slug) or slug in seen:
            continue
        seen.add(slug)
        slugs.append(slug)
    return slugs


def extract_pack_urls_from_html(document: str) -> list[str]:
    tree = html.fromstring(document)
    urls: list[str] = []
    seen: set[str] = set()
    for href in tree.xpath("//a/@href"):
        absolute = urljoin(SITE, str(href))
        parsed = urlsplit(absolute)
        path = parsed.path.rstrip("/")
        if parsed.hostname not in WHOLE_SITE_TARGETS:
            continue
        if not path.startswith("/directory/") or path.startswith(CHARACTER_PREFIX) or path.count("/") != 2:
            continue
        url = f"{SITE}{path}"
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _is_whole_site_target(target: str) -> bool:
    normalized = target.strip().lower().rstrip("/")
    if normalized in WHOLE_SITE_TARGETS:
        return True
    if "://" not in normalized:
        return False
    parsed = urlsplit(normalized)
    return parsed.scheme in {"http", "https"} and parsed.hostname in WHOLE_SITE_TARGETS and parsed.path.rstrip("/") in {"", "/directory"}


def _unique_characters(characters: Iterable[CharacterRef]) -> list[CharacterRef]:
    unique: list[CharacterRef] = []
    seen: set[tuple[str, str]] = set()
    for character in characters:
        key = (character.source, character.id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(character)
    return unique


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _asset_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "https" or _origin(value) not in ASSET_HOSTS:
        return None
    return value


def _parse_sprites(value: object) -> dict[str, SpriteRegion]:
    if not isinstance(value, dict):
        return {}
    sprites: dict[str, SpriteRegion] = {}
    for raw_path, raw_region in value.items():
        if not isinstance(raw_path, str) or not isinstance(raw_region, dict):
            continue
        normalized = normalize_asset_ref(raw_path)
        if normalized is None:
            continue
        path, absolute_url = normalized
        if absolute_url is not None or not path.lower().endswith(".png"):
            continue
        try:
            x = int(raw_region["x"])
            y = int(raw_region["y"])
            width = int(raw_region["width"])
            height = int(raw_region["height"])
        except (KeyError, TypeError, ValueError):
            continue
        if min(x, y) < 0 or min(width, height) <= 0:
            continue
        sprites[path] = SpriteRegion(path, x, y, width, height)
    return sprites
