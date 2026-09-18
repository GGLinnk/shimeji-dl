from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

IMAGE_SUFFIXES = {".png", ".gif", ".jpg", ".jpeg", ".webp", ".bmp"}


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)


def atomic_write_json(path: Path, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8") + b"\n"
    atomic_write(path, payload)


def normalize_asset_ref(value: str) -> tuple[str, str | None] | None:
    """Return a safe local POSIX path and optional absolute source URL."""
    raw = value.strip()
    if not raw:
        return None

    parsed = urlsplit(raw)
    absolute_url: str | None = None
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        absolute_url = raw
        candidate = unquote(parsed.path)
        # Absolute URLs are uncommon in Shimeji XML. Keep only the file name
        # rather than mirroring a remote site's entire path locally.
        candidate = PurePosixPath(candidate).name
    else:
        candidate = unquote(raw.split("?", 1)[0].split("#", 1)[0])

    candidate = candidate.replace("\\", "/").lstrip("/")
    while candidate.startswith("./"):
        candidate = candidate[2:]
    if candidate.lower().startswith("img/"):
        candidate = candidate[4:]

    path = PurePosixPath(candidate)
    if not candidate or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    if ":" in path.parts[0]:
        return None
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        return None

    return path.as_posix(), absolute_url


def quote_asset_path(path: str) -> str:
    return "/".join(quote(part, safe="") for part in PurePosixPath(path).parts)


def looks_like_image(data: bytes, path: str, content_type: str | None = None) -> bool:
    if not data:
        return False

    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if suffix == ".gif":
        return data.startswith((b"GIF87a", b"GIF89a"))
    if suffix in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if suffix == ".webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if suffix == ".bmp":
        return data.startswith(b"BM")

    return bool(content_type and content_type.lower().startswith("image/"))


def is_valid_local_image(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    return looks_like_image(data, path.name)


def compress_numbers(values: list[int]) -> list[str]:
    if not values:
        return []
    nums = sorted(set(values))
    ranges: list[str] = []
    start = previous = nums[0]
    for number in nums[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = number
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ranges


def collect_images(root: Path) -> list[str]:
    result: list[str] = []
    if not root.exists():
        return result
    for path in root.rglob("*"):
        if not path.is_file() or "conf" in path.relative_to(root).parts:
            continue
        if path.suffix.lower() in IMAGE_SUFFIXES and is_valid_local_image(path):
            result.append(path.relative_to(root).as_posix())
    return sorted(result, key=natural_key)


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]
