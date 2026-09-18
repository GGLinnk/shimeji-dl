from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..errors import ExtractorError
from ..http import AsyncHTTP
from ..models import Character
from ..utils import title_from_slug

BASE = "https://shimejis.xyz"
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]+$", re.IGNORECASE)
_PREVIEW_RE = re.compile(
    r"https://sprites?\.shimejis\.xyz/directory/[^\"'<>\s]+?/img/[^\"'<>\s]+",
    re.IGNORECASE,
)


class ShimejisXYZExtractor:
    def __init__(self, http: AsyncHTTP) -> None:
        self.http = http

    async def extract(self, value: str) -> list[Character]:
        value = value.strip()
        parsed = urlparse(value)

        if parsed.scheme in {"http", "https"}:
            host = parsed.hostname or ""
            if host not in {"shimejis.xyz", "www.shimejis.xyz"}:
                raise ExtractorError(f"unsupported host: {host}")

            path = parsed.path.rstrip("/")
            marker = "/directory/shimeji/"
            if marker in path:
                slug = path.split(marker, 1)[1].split("/", 1)[0]
                if not slug:
                    raise ExtractorError("missing character slug")
                char = Character(slug=slug, page_url=f"{BASE}/directory/shimeji/{slug}")
                return [await self.enrich(char)]

            if path.startswith("/directory/"):
                return await self._extract_pack(value)

            raise ExtractorError(f"unsupported shimejis.xyz URL: {value}")

        if _SLUG_RE.fullmatch(value):
            char = Character(slug=value, page_url=f"{BASE}/directory/shimeji/{value}")
            return [await self.enrich(char)]

        raise ExtractorError(f"not a shimejis.xyz URL or slug: {value}")

    async def _extract_pack(self, url: str) -> list[Character]:
        html = await self.http.text(url)
        if html is None:
            raise ExtractorError(f"could not load pack: {url}")
        chars = self.parse_pack_html(html, pack_url=url)
        if not chars:
            raise ExtractorError(f"no characters found in pack: {url}")
        return chars

    @staticmethod
    def parse_pack_html(html: str, *, pack_url: str) -> list[Character]:
        soup = BeautifulSoup(html, "html.parser")
        found: list[Character] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = str(anchor.get("href"))
            match = re.search(r"/directory/shimeji/([^/?#]+)", href)
            if not match:
                continue
            slug = match.group(1)
            if slug in seen:
                continue
            seen.add(slug)
            name = anchor.get_text(" ", strip=True) or None
            guessed_name, guessed_artist = title_from_slug(slug)
            found.append(
                Character(
                    slug=slug,
                    page_url=urljoin(BASE, f"/directory/shimeji/{slug}"),
                    name=name or guessed_name,
                    artist=guessed_artist,
                    pack_url=pack_url,
                )
            )
        return found

    async def enrich(self, char: Character) -> Character:
        html = await self.http.text(char.page_url, optional=True)
        if not html:
            return char

        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(" ", strip=True)
            title = re.sub(r"\s+shimeji\s*$", "", title, flags=re.IGNORECASE)
            if title:
                char.name = title

        # The page renders "artist: <a>Creator</a>". Find the parent text,
        # rather than relying on CSS class names that may change.
        for link in soup.find_all("a"):
            parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""
            if re.search(r"\bartist\s*:", parent_text, re.IGNORECASE):
                artist = link.get_text(" ", strip=True)
                if artist:
                    char.artist = artist
                    break

        candidates: list[str] = []
        for tag in soup.find_all(["img", "a"]):
            for attr in ("src", "data-src", "href"):
                value = tag.get(attr)
                if isinstance(value, str) and "shimejis.xyz" in value and "/img/" in value:
                    candidates.append(value)
        candidates.extend(_PREVIEW_RE.findall(html))

        for value in candidates:
            absolute = urljoin(char.page_url, value)
            parsed = urlparse(absolute)
            if parsed.hostname in {"sprite.shimejis.xyz", "sprites.shimejis.xyz"} and "/img/" in parsed.path:
                char.preview_url = absolute
                break

        return char
