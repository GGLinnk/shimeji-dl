from __future__ import annotations

import json
import os
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

IMAGE_SUFFIXES = {".png", ".gif", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_SUFFIXES = {".wav", ".aif", ".aiff", ".au", ".mp3", ".ogg"}


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_bytes(data)
    os.replace(part, path)


def atomic_write_json(path: Path, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    atomic_write(path, payload)


def normalize_resource_ref(value: str) -> tuple[str, str | None] | None:
    raw = value.strip()
    if not raw:
        return None

    parsed = urlsplit(raw)
    absolute_url: str | None = None
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        absolute_url = raw
        candidate = PurePosixPath(unquote(parsed.path)).name
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

    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return path.as_posix(), absolute_url
    if suffix in AUDIO_SUFFIXES:
        if not path.parts or path.parts[0].lower() != "sound":
            path = PurePosixPath("sound") / path
        return path.as_posix(), absolute_url
    return None


def normalize_asset_ref(value: str) -> tuple[str, str | None] | None:
    normalized = normalize_resource_ref(value)
    if normalized is None or PurePosixPath(normalized[0]).suffix.lower() not in IMAGE_SUFFIXES:
        return None
    return normalized


def quote_asset_path(path: str) -> str:
    return "/".join(quote(part, safe="") for part in PurePosixPath(path).parts)


def looks_like_image(data: bytes, path: str, content_type: str | None = None) -> bool:
    if not data:
        return False
    suffix = PurePosixPath(path).suffix.lower()
    signatures = {
        ".png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
        ".gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
        ".jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
        ".jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
        ".webp": lambda b: len(b) >= 12 and b[:4] == b"RIFF" and b[8:12] == b"WEBP",
        ".bmp": lambda b: b.startswith(b"BM"),
    }
    checker = signatures.get(suffix)
    return checker(data) if checker else bool(content_type and content_type.lower().startswith("image/"))


def looks_like_audio(data: bytes, path: str, content_type: str | None = None) -> bool:
    if not data:
        return False
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".wav":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if suffix in {".aif", ".aiff"}:
        return len(data) >= 12 and data[:4] == b"FORM" and data[8:12] in {b"AIFF", b"AIFC"}
    if suffix == ".au":
        return data.startswith(b".snd")
    if suffix == ".ogg":
        return data.startswith(b"OggS")
    if suffix == ".mp3":
        return data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    return bool(content_type and content_type.lower().startswith("audio/"))


def looks_like_resource(data: bytes, path: str, content_type: str | None = None) -> bool:
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return looks_like_image(data, path, content_type)
    if suffix in AUDIO_SUFFIXES:
        return looks_like_audio(data, path, content_type)
    return False


def is_valid_local_image(path: Path) -> bool:
    try:
        return looks_like_image(path.read_bytes(), path.name)
    except OSError:
        return False


def is_valid_local_resource(path: Path) -> bool:
    try:
        return looks_like_resource(path.read_bytes(), path.name)
    except OSError:
        return False


def collect_images(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        (
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
            and "conf" not in path.relative_to(root).parts
            and path.suffix.lower() in IMAGE_SUFFIXES
            and is_valid_local_image(path)
        ),
        key=natural_key,
    )


def collect_sounds(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(
        (
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in AUDIO_SUFFIXES
            and is_valid_local_resource(path)
        ),
        key=natural_key,
    )


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


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
