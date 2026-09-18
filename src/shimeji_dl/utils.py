from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlparse

WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def title_from_slug(slug: str) -> tuple[str, str | None]:
    raw = slug
    if raw.startswith("undertale-"):
        raw = raw[len("undertale-"):]
    parts = raw.split("-by-", 1)
    name = " ".join(word.capitalize() for word in parts[0].split("-") if word)
    artist = None
    if len(parts) == 2:
        artist = " ".join(word.capitalize() for word in parts[1].split("-") if word)
    return name or slug, artist


def safe_folder_name(value: str, *, fallback: str = "shimeji") -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", value).strip().rstrip(".")
    value = re.sub(r"\s+", " ", value)
    if not value:
        value = fallback
    if value.upper() in WINDOWS_RESERVED:
        value = f"_{value}"
    return value[:180]


def character_folder_name(slug: str, name: str | None, artist: str | None) -> str:
    guessed_name, guessed_artist = title_from_slug(slug)
    base = (name or guessed_name).strip()
    creator = (artist or guessed_artist or "").strip()
    if creator and creator.casefold() not in base.casefold():
        base = f"{base} - {creator}"
    return safe_folder_name(base, fallback=slug)


def sanitize_asset_path(value: str) -> str:
    """Convert an XML Image path into a safe relative POSIX path."""
    value = value.strip().replace("\\", "/")
    if not value:
        raise ValueError("empty asset path")

    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        raise ValueError("absolute URLs are not accepted as asset paths")

    value = value.split("?", 1)[0].split("#", 1)[0].lstrip("/")
    parts = [p for p in PurePosixPath(value).parts if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise ValueError("unsafe asset path")
    return "/".join(parts)


def encoded_asset_path(relative_path: str) -> str:
    return "/".join(quote(part, safe="") for part in PurePosixPath(relative_path).parts)


def path_for_asset(root: Path, relative_path: str) -> Path:
    parts = PurePosixPath(relative_path).parts
    return root.joinpath(*parts)
