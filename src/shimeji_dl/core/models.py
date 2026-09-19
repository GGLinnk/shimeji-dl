from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CharacterRef:
    source: str
    id: str
    source_url: str
    title: str | None = None


@dataclass(frozen=True, slots=True)
class AssetRef:
    value: str
    path: str
    absolute_url: str | None = None


@dataclass(slots=True)
class ConfigResource:
    name: str
    data: bytes
    source_url: str | None
    cached: bool = False
    asset_refs: list[AssetRef] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SpriteRegion:
    path: str
    x: int
    y: int
    width: int
    height: int


@dataclass(slots=True)
class SourceManifest:
    source_url: str
    authoritative: bool = False
    configs: dict[str, bytes] = field(default_factory=dict)
    spritesheet_url: str | None = None
    sprites: dict[str, SpriteRegion] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def asset_refs(self) -> list[AssetRef]:
        return [AssetRef(value=path, path=path) for path in self.sprites]


@dataclass(frozen=True, slots=True)
class MissingAsset:
    path: str
    kind: str
    tried_urls: tuple[str, ...]


@dataclass(slots=True)
class ProbeReport:
    mode: str
    anchors: list[int] = field(default_factory=list)
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
    asset_paths: list[str]
    discovery: str
    configs: dict[str, ConfigResource | None]
    referenced_missing: list[MissingAsset]
    probe: ProbeReport
    usable: bool
    manifest: SourceManifest | None = None
    atlas_paths: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def complete(self) -> bool:
        return self.error is None and self.usable and not self.referenced_missing

    @property
    def failed(self) -> bool:
        return not self.complete

    @property
    def retryable(self) -> bool:
        if self.error or not self.usable:
            return True
        return any(item.kind != "source-missing" for item in self.referenced_missing)

    @property
    def strict_ok(self) -> bool:
        return self.complete
