from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal
from urllib.parse import quote, unquote, urlsplit

import pathvalidate

from .asset_path_escapes_destination import AssetPathEscapesDestination

# Below the 255-byte name limit most filesystems share, and below Windows'
# legacy MAX_PATH once the value is joined under a destination directory.
MAX_ASSET_PATH_LENGTH = 240


@dataclass(frozen=True, slots=True)
class ResourceSignature:
    kind: Literal["image", "audio"]
    matches: Callable[[bytes], bool]


def _matches_png(data: bytes) -> bool:
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def _matches_gif(data: bytes) -> bool:
    return data.startswith((b"GIF87a", b"GIF89a"))


def _matches_jpeg(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff")


def _matches_webp(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"


# Every DIB header size the BMP format has standardized.
_BMP_DIB_HEADER_SIZES = frozenset({12, 16, 40, 52, 56, 64, 108, 124})
# "BM" (2 bytes) + file size and reserved fields (10 bytes) + DIB header
# size field itself (4 bytes).
_BMP_MIN_HEAD_BYTES = 18


def _matches_bmp(data: bytes) -> bool:
    if len(data) < _BMP_MIN_HEAD_BYTES or not data.startswith(b"BM"):
        return False
    dib_header_size = int.from_bytes(data[14:18], "little")
    return dib_header_size in _BMP_DIB_HEADER_SIZES


def _matches_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def _matches_aiff(data: bytes) -> bool:
    return len(data) >= 12 and data[:4] == b"FORM" and data[8:12] in {b"AIFF", b"AIFC"}


def _matches_au(data: bytes) -> bool:
    # ".snd" is the standard big-endian AU magic. "dns." is its byte-swapped
    # little-endian variant, a supported format, not a stricter check.
    return data.startswith(b".snd") or data.startswith(b"dns.")


# MPEG audio frame header, byte 1: version bits 01 is the reserved value.
_MP3_RESERVED_VERSION = 0b01
# MPEG audio frame header, byte 1: layer bits 00 is the reserved value.
_MP3_RESERVED_LAYER = 0b00
# MPEG audio frame header, byte 2: bitrate index 1111 is invalid;
# index 0000 is the legal free-format marker.
_MP3_INVALID_BITRATE_INDEX = 0b1111
_MP3_MIN_HEAD_BYTES = 3


def _matches_mp3(data: bytes) -> bool:
    if data.startswith(b"ID3"):
        return True
    if len(data) < _MP3_MIN_HEAD_BYTES:
        return False
    if data[0] != 0xFF or data[1] & 0xE0 != 0xE0:
        return False
    version = (data[1] >> 3) & 0b11
    layer = (data[1] >> 1) & 0b11
    bitrate_index = (data[2] >> 4) & 0b1111
    return (
        version != _MP3_RESERVED_VERSION
        and layer != _MP3_RESERVED_LAYER
        and bitrate_index != _MP3_INVALID_BITRATE_INDEX
    )


_OGG_MIN_HEAD_BYTES = 8
# Ogg page header type flag: only the low 3 bits are defined.
_OGG_MAX_HEADER_TYPE = 0b111


def _matches_ogg(data: bytes) -> bool:
    return (
        len(data) >= _OGG_MIN_HEAD_BYTES
        and data[:4] == b"OggS"
        and data[4] == 0
        and data[5] <= _OGG_MAX_HEADER_TYPE
    )


RESOURCE_SIGNATURES: dict[str, ResourceSignature] = {
    ".png": ResourceSignature("image", _matches_png),
    ".gif": ResourceSignature("image", _matches_gif),
    ".jpg": ResourceSignature("image", _matches_jpeg),
    ".jpeg": ResourceSignature("image", _matches_jpeg),
    ".webp": ResourceSignature("image", _matches_webp),
    ".bmp": ResourceSignature("image", _matches_bmp),
    ".wav": ResourceSignature("audio", _matches_wav),
    ".aif": ResourceSignature("audio", _matches_aiff),
    ".aiff": ResourceSignature("audio", _matches_aiff),
    ".au": ResourceSignature("audio", _matches_au),
    ".mp3": ResourceSignature("audio", _matches_mp3),
    ".ogg": ResourceSignature("audio", _matches_ogg),
}

IMAGE_SUFFIXES = frozenset(suffix for suffix, sig in RESOURCE_SIGNATURES.items() if sig.kind == "image")
AUDIO_SUFFIXES = frozenset(suffix for suffix, sig in RESOURCE_SIGNATURES.items() if sig.kind == "audio")

# Must stay at or above the largest per-format head requirement (18 bytes,
# .bmp); a smaller value silently loosens that format's signature check
# rather than merely reading less.
RESOURCE_HEAD_BYTES = 64


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".part",
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
        handle.close()
        os.replace(temp_path, path)
    except BaseException:
        handle.close()
        temp_path.unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, value: object) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    atomic_write(path, payload)


def confined_asset_path(dest: Path, path: str) -> Path:
    resolved_dest = dest.resolve()
    resolved = dest.joinpath(*path.split("/")).resolve()
    if not resolved.is_relative_to(resolved_dest):
        raise AssetPathEscapesDestination(dest, path)
    return resolved


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

    # Split on the raw string, never on PurePosixPath.parts: pathlib
    # silently collapses "//" and "/./" segments, which would hide them
    # from this check.
    segments = candidate.split("/")
    if not candidate or any(segment in {"", ".", ".."} for segment in segments):
        return None
    try:
        pathvalidate.validate_filepath(candidate, platform="universal", max_len=MAX_ASSET_PATH_LENGTH)
    except pathvalidate.ValidationError:
        return None

    path = PurePosixPath(candidate)
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


def looks_like_resource(data: bytes, path: str) -> bool:
    if not data:
        return False
    suffix = PurePosixPath(path).suffix.lower()
    signature = RESOURCE_SIGNATURES.get(suffix)
    return bool(signature and signature.matches(data))


def is_valid_local_resource(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            head = handle.read(RESOURCE_HEAD_BYTES)
    except OSError:
        return False
    return looks_like_resource(head, path.name)


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
            and is_valid_local_resource(path)
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
