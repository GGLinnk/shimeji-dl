from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class Character:
    slug: str
    page_url: str
    name: str | None = None
    artist: str | None = None
    preview_url: str | None = None
    pack_url: str | None = None


@dataclass(slots=True)
class FileRecord:
    relative_path: str
    url: str
    status: str
    size: int = 0
    sha256: str | None = None


@dataclass(slots=True)
class CharacterReport:
    character: Character
    destination: Path
    ok: bool
    sprite_base: str | None = None
    discovery_mode: str | None = None
    actions_url: str | None = None
    behaviors_url: str | None = None
    xml_images: list[str] = field(default_factory=list)
    files: list[FileRecord] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
