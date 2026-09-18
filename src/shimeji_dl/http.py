from __future__ import annotations

import asyncio
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
import hashlib
import os
import random
import time
from typing import Callable

import httpx

from .errors import FetchError


@dataclass(slots=True)
class Fetched:
    requested_url: str
    final_url: str
    status_code: int
    headers: httpx.Headers
    content: bytes


@dataclass(slots=True)
class Saved:
    status: str
    size: int
    sha256: str


class AsyncHTTP:
    def __init__(
        self,
        *,
        concurrency: int = 12,
        timeout: float = 20.0,
        retries: int = 3,
        user_agent: str | None = None,
    ) -> None:
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._retries = max(0, retries)
        self._client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10.0)),
            headers={
                "User-Agent": user_agent
                or "Mozilla/5.0 (compatible; shimeji-dl/0.1; +https://shimejis.xyz/)",
                "Accept": "*/*",
                "Accept-Language": "en-US,en;q=0.8",
            },
            limits=httpx.Limits(
                max_connections=max(4, concurrency),
                max_keepalive_connections=max(2, concurrency),
            ),
        )

    async def __aenter__(self) -> "AsyncHTTP":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
        if response is not None:
            retry_after = response.headers.get("Retry-After")
            if retry_after:
                try:
                    return min(30.0, max(0.0, float(retry_after)))
                except ValueError:
                    try:
                        dt = parsedate_to_datetime(retry_after)
                        return min(30.0, max(0.0, dt.timestamp() - time.time()))
                    except Exception:
                        pass
        return min(8.0, (0.5 * (2**attempt)) + random.random() * 0.25)

    async def get(self, url: str, *, optional: bool = False) -> Fetched | None:
        last_error: Exception | None = None
        retry_status = {408, 425, 429, 500, 502, 503, 504}

        for attempt in range(self._retries + 1):
            response: httpx.Response | None = None
            try:
                async with self._sem:
                    response = await self._client.get(url)

                if 200 <= response.status_code < 300:
                    return Fetched(
                        requested_url=url,
                        final_url=str(response.url),
                        status_code=response.status_code,
                        headers=response.headers,
                        content=response.content,
                    )

                if response.status_code in retry_status and attempt < self._retries:
                    await asyncio.sleep(self._retry_delay(response, attempt))
                    continue

                if optional:
                    return None
                raise FetchError(f"HTTP {response.status_code} for {url}")

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                if attempt < self._retries:
                    await asyncio.sleep(self._retry_delay(response, attempt))
                    continue
                if optional:
                    return None
                raise FetchError(f"network error for {url}: {exc}") from exc

        if optional:
            return None
        raise FetchError(f"could not fetch {url}: {last_error or 'unknown error'}")

    async def text(self, url: str, *, optional: bool = False) -> str | None:
        fetched = await self.get(url, optional=optional)
        if fetched is None:
            return None
        encoding = "utf-8"
        content_type = fetched.headers.get("content-type", "")
        match = __import__("re").search(r"charset=([^;\s]+)", content_type, __import__("re").I)
        if match:
            encoding = match.group(1).strip('"\'')
        return fetched.content.decode(encoding, errors="replace")

    async def save_bytes(
        self,
        data: bytes,
        destination: Path,
        *,
        overwrite: bool = False,
    ) -> Saved:
        destination.parent.mkdir(parents=True, exist_ok=True)

        if destination.exists() and not overwrite:
            existing = destination.read_bytes()
            return Saved("existing", len(existing), hashlib.sha256(existing).hexdigest())

        digest = hashlib.sha256(data).hexdigest()
        tmp = destination.with_name(f".{destination.name}.{os.getpid()}.part")
        tmp.write_bytes(data)
        os.replace(tmp, destination)
        return Saved("downloaded", len(data), digest)

    async def download(
        self,
        url: str,
        destination: Path,
        *,
        overwrite: bool = False,
        validator: Callable[[Fetched], bool] | None = None,
        optional: bool = False,
    ) -> Saved | None:
        if destination.exists() and not overwrite:
            existing = destination.read_bytes()
            return Saved("existing", len(existing), hashlib.sha256(existing).hexdigest())

        fetched = await self.get(url, optional=optional)
        if fetched is None:
            return None
        if validator is not None and not validator(fetched):
            if optional:
                return None
            raise FetchError(f"unexpected payload at {url}")
        return await self.save_bytes(fetched.content, destination, overwrite=True)
