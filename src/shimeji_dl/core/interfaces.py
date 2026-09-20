from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from typing import Protocol

from .http import HttpClient
from .models import (
    AssetRef,
    CharacterRef,
    CharacterResult,
    ConfigResource,
    SourceManifest,
)


class ConfigFormat(Protocol):
    def is_valid(self, data: bytes) -> bool: ...

    def extract_asset_refs(self, data: bytes) -> list[AssetRef]: ...


class SourceAdapter(Protocol):
    key: str

    @property
    def config_names(self) -> Sequence[str]: ...

    @classmethod
    def suitable(cls, target: str) -> bool: ...

    def confirmation_message(self, target: str) -> str | None: ...

    async def extract(self, client: HttpClient, target: str) -> list[CharacterRef]: ...

    def request_headers(self) -> dict[str, str]: ...

    def config_candidates(self, character: CharacterRef, name: str) -> list[str]: ...

    def asset_candidates(self, character: CharacterRef, ref: AssetRef) -> list[str]: ...

    def numeric_asset(self, character: CharacterRef, index: int) -> AssetRef: ...

    def prioritize(self, character: CharacterRef, configs: Iterable[ConfigResource | None]) -> None: ...


class ManifestSourceAdapter(ABC):
    """Optional source capability for an authoritative per-character manifest.

    A source declares this capability by inheriting from it explicitly, so an incompatible `fetch_manifest` override is a mypy error at that source's own definition, never a runtime surprise discovered only because an unrelated attribute happened to share the name.
    """

    @abstractmethod
    async def fetch_manifest(
        self,
        client: HttpClient,
        character: CharacterRef,
        *,
        report_rejection: Callable[[str], None],
    ) -> SourceManifest | None: ...


class Reporter(Protocol):
    def extraction(self, source: str, target: str) -> None: ...

    def start(self, characters: Sequence[CharacterRef]) -> None: ...

    def character_started(self, character: CharacterRef) -> None: ...

    def character_phase(self, character: CharacterRef, phase: str, detail: str = "") -> None: ...

    def character_finished(self, result: CharacterResult) -> None: ...

    def warning(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def verbose(self, message: str) -> None: ...

    def confirm(self, message: str, *, default: bool = False) -> bool: ...

    def finish(self) -> None: ...
