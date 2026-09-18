from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from ..client import AsyncFetcher
from ..models import CharacterRef
from .base import Extractor

SITE = "https://shimejis.xyz"
CHARACTER_PREFIX = "/directory/shimeji/"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class _CharacterLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.slugs: list[str] = []
        self._seen: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        if not href:
            return
        path = urlsplit(urljoin(SITE, href)).path.rstrip("/")
        if not path.startswith(CHARACTER_PREFIX):
            return
        slug = path[len(CHARACTER_PREFIX) :]
        if "/" in slug or not SLUG_RE.fullmatch(slug) or slug in self._seen:
            return
        self._seen.add(slug)
        self.slugs.append(slug)


class ShimejisXYZExtractor(Extractor):
    key = "shimejis.xyz"

    @classmethod
    def suitable(cls, target: str) -> bool:
        if "://" not in target:
            return bool(SLUG_RE.fullmatch(target.strip().lower()))
        parsed = urlsplit(target)
        return parsed.scheme in {"http", "https"} and parsed.hostname in {
            "shimejis.xyz",
            "www.shimejis.xyz",
        }

    async def extract(self, fetcher: AsyncFetcher, target: str) -> list[CharacterRef]:
        normalized = target.strip()
        if "://" not in normalized:
            slug = normalized.lower()
            if slug.endswith("-shimeji-pack"):
                return await self._extract_pack(fetcher, f"{SITE}/directory/{slug}")
            return [self._character(slug)]

        parsed = urlsplit(normalized)
        path = parsed.path.rstrip("/")
        if path.startswith(CHARACTER_PREFIX):
            slug = path[len(CHARACTER_PREFIX) :]
            if not SLUG_RE.fullmatch(slug):
                raise ValueError(f"invalid shimeji slug in URL: {target}")
            return [self._character(slug)]

        if path.startswith("/directory/") and path.count("/") == 2:
            return await self._extract_pack(fetcher, f"{SITE}{path}")

        raise ValueError(f"unsupported shimejis.xyz URL: {target}")

    async def _extract_pack(self, fetcher: AsyncFetcher, url: str) -> list[CharacterRef]:
        html = await fetcher.get_text(url)
        parser = _CharacterLinkParser()
        parser.feed(html)
        if not parser.slugs:
            raise ValueError(f"no character links found in pack: {url}")
        return [self._character(slug) for slug in parser.slugs]

    @staticmethod
    def _character(slug: str) -> CharacterRef:
        return CharacterRef(
            extractor=ShimejisXYZExtractor.key,
            id=slug,
            source_url=f"{SITE}{CHARACTER_PREFIX}{slug}",
        )


def extract_slugs_from_html(html: str) -> list[str]:
    """Public helper used by tests and future tooling."""
    parser = _CharacterLinkParser()
    parser.feed(html)
    return parser.slugs
