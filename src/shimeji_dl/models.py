from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CharacterRef:
    extractor: str
    id: str
    source_url: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class ImageRef:
    value: str
    path: str
    absolute_url: str | None = None


@dataclass(slots=True)
class ConfigResource:
    name: str
    data: bytes
    source_url: str | None
    cached: bool = False
    image_refs: list[ImageRef] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class MissingAsset:
    path: str
    kind: str
    tried_urls: tuple[str, ...]


@dataclass(slots=True)
class ProbeReport:
    mode: str
    xml_anchors: list[int] = field(default_factory=list)
    hits: list[int] = field(default_factory=list)
    extra_hits: list[str] = field(default_factory=list)
    misses: list[int] = field(default_factory=list)
    requests: int = 0
    gallop_probes: int = 0
    bisect_probes: int = 0
    fill_probes: int = 0
    quiescence_probes: int = 0
    quiescence_span: int = 0
    highest_hit: int | None = None
    highest_tested: int | None = None
    stop_reason: str = "disabled"


@dataclass(slots=True)
class CharacterResult:
    character: CharacterRef
    output_dir: str
    sprite_paths: list[str]
    discovery: str
    actions: ConfigResource | None
    behaviors: ConfigResource | None
    referenced_missing: list[MissingAsset]
    probe: ProbeReport
    usable: bool

    @property
    def strict_ok(self) -> bool:
        return self.usable and not self.referenced_missing
