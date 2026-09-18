from __future__ import annotations

from abc import ABC, abstractmethod

from ..client import AsyncFetcher
from ..models import CharacterRef


class Extractor(ABC):
    key = "base"

    @classmethod
    @abstractmethod
    def suitable(cls, target: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def extract(self, fetcher: AsyncFetcher, target: str) -> list[CharacterRef]:
        raise NotImplementedError
