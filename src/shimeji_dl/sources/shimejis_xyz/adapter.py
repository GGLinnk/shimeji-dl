from __future__ import annotations

import asyncio
import re
from collections.abc import Callable, Iterable
from urllib.parse import urljoin, urlsplit

import httpx
import msgspec
from lxml import html

from ...core.http import HttpClient
from ...core.http_error import HttpError
from ...core.models import (
    AssetRef,
    CharacterRef,
    ConfigResource,
    SourceManifest,
    SpriteRegion,
)
from ...core.storage import normalize_asset_ref, quote_asset_path
from .manifest_rejection import (
    InvalidSpritePath,
    InvalidSpriteRegion,
    SpriteAbsoluteUrlPresent,
    SpriteRejection,
    SpriteWrongSuffix,
)
from .manifest_schema import (
    BoundedConfigXml,
    BoundedUrl,
    ManifestEnvelope,
    ManifestMetadataWire,
    SpriteRegionWire,
)

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

    async def fetch_manifest(
        self,
        client: HttpClient,
        character: CharacterRef,
        *,
        report_rejection: Callable[[str], None] = lambda message: None,
    ) -> SourceManifest | None:
        url = f"{SITE}/api/shimeji/{character.id}/configuration"
        response = await client.get(url, optional=True, headers=self.request_headers())
        if response is None:
            report_rejection(f"manifest unavailable: {url}")
            return None

        try:
            envelope = msgspec.json.decode(response.content, type=ManifestEnvelope)
        except msgspec.ValidationError as exc:
            report_rejection(f"manifest envelope has the wrong shape: {url}: {exc}")
            return None
        except msgspec.DecodeError as exc:
            report_rejection(f"manifest is not valid JSON: {url}: {exc}")
            return None

        config_fields: dict[str, msgspec.Raw] = {
            "actions.xml": envelope.actions,
            "behaviors.xml": envelope.behaviors,
            "info.xml": envelope.info,
        }
        configs = {
            filename: text.encode("utf-8")
            for filename in self.config_names
            if (text := _decode_config_text(config_fields[filename], filename, report_rejection)) is not None
        }
        sprites = _parse_sprites(envelope.sprites, report_rejection)
        spritesheet_url = _asset_url(_decode_spritesheet_url(envelope.spritesheet, report_rejection))
        metadata = _decode_metadata(envelope.metadata, report_rejection)

        if spritesheet_url:
            origin = _origin(spritesheet_url)
            if origin in ASSET_HOSTS:
                self._preferred_hosts[character.id] = (origin,) + tuple(
                    host for host in ASSET_HOSTS if host != origin
                )

        if not configs and not sprites:
            report_rejection(f"manifest carries neither a usable config nor a sprite: {url}")
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
            trusted = _asset_url(ref.absolute_url)
            return [trusted] if trusted else []

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
        async with asyncio.TaskGroup() as task_group:
            tasks = [task_group.create_task(self._extract_pack_or_skip(client, url)) for url in packs]
        groups = [task.result() for task in tasks]
        return _unique_characters(character for group in groups for character in group)

    async def _extract_pack_or_skip(self, client: HttpClient, url: str) -> list[CharacterRef]:
        """Fetch one pack page as part of a whole-catalogue scan.

        A single pack page failing to fetch or decode must cost that pack,
        never the sibling packs already running in the same task group.
        """
        try:
            return await self._extract_pack(client, url)
        except HttpError:
            return []

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
    parsed = httpx.URL(url)
    port_suffix = "" if parsed.port is None else f":{parsed.port}"
    return f"{parsed.scheme}://{parsed.host}{port_suffix}"


def _asset_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = httpx.URL(value)
    except httpx.InvalidURL:
        return None
    if parsed.scheme != "https" or parsed.userinfo or _origin(value) not in ASSET_HOSTS:
        return None
    return value


def _decode_config_text(
    raw: msgspec.Raw,
    field_name: str,
    report_rejection: Callable[[str], None],
) -> str | None:
    try:
        return msgspec.json.decode(raw, type=BoundedConfigXml | None)
    except msgspec.ValidationError as exc:
        report_rejection(f"manifest {field_name} field rejected: {exc}")
        return None


def _decode_spritesheet_url(raw: msgspec.Raw, report_rejection: Callable[[str], None]) -> str | None:
    try:
        return msgspec.json.decode(raw, type=BoundedUrl | None)
    except msgspec.ValidationError as exc:
        report_rejection(f"manifest spritesheet field rejected: {exc}")
        return None


def _decode_metadata(raw: msgspec.Raw, report_rejection: Callable[[str], None]) -> dict[str, object]:
    try:
        wire = msgspec.json.decode(raw, type=ManifestMetadataWire | None)
    except msgspec.ValidationError as exc:
        report_rejection(f"manifest metadata field rejected: {exc}")
        return {}
    if wire is None:
        return {}
    return {name: value for name, value in msgspec.structs.asdict(wire).items() if value is not None}


def _validate_sprite_entry(key: str, raw_region: msgspec.Raw) -> SpriteRegion:
    raw_value = bytes(raw_region)
    normalized = normalize_asset_ref(key)
    if normalized is None:
        raise InvalidSpritePath(key, raw_value)
    path, absolute_url = normalized
    if absolute_url is not None:
        raise SpriteAbsoluteUrlPresent(key, raw_value)
    if not path.lower().endswith(".png"):
        raise SpriteWrongSuffix(key, raw_value)
    try:
        region = msgspec.json.decode(raw_region, type=SpriteRegionWire)
    except msgspec.ValidationError as exc:
        raise InvalidSpriteRegion(key, raw_value) from exc
    return SpriteRegion(path, region.x, region.y, region.width, region.height)


def _parse_sprites(raw: msgspec.Raw, report_rejection: Callable[[str], None]) -> dict[str, SpriteRegion]:
    try:
        entries = msgspec.json.decode(raw, type=dict[str, msgspec.Raw] | None)
    except msgspec.ValidationError as exc:
        report_rejection(f"manifest sprites field is not an object: {exc}")
        return {}
    if entries is None:
        return {}

    sprites: dict[str, SpriteRegion] = {}
    for key, raw_region in entries.items():
        try:
            region = _validate_sprite_entry(key, raw_region)
        except SpriteRejection as rejection:
            cause = f": {rejection.__cause__}" if rejection.__cause__ is not None else ""
            report_rejection(f"{rejection}{cause}")
            continue
        sprites[region.path] = region
    return sprites
