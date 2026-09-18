from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx


RETRIABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
OPTIONAL_STATUS = {400, 401, 403, 404, 405, 410}


@dataclass(frozen=True, slots=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    content_type: str | None


class FetchError(RuntimeError):
    pass


class AsyncFetcher:
    def __init__(
        self,
        *,
        connections: int,
        timeout: float,
        retries: int,
        user_agent: str,
    ) -> None:
        self._semaphore = asyncio.Semaphore(connections)
        self._retries = max(0, retries)
        limits = httpx.Limits(max_connections=connections, max_keepalive_connections=connections)
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
            limits=limits,
            headers={
                "User-Agent": user_agent,
                "Accept": "*/*",
                "Referer": "https://shimejis.xyz/",
            },
        )

    async def __aenter__(self) -> "AsyncFetcher":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(self, url: str, *, optional: bool = False) -> FetchResult | None:
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                async with self._semaphore:
                    response = await self._client.get(url)

                if 200 <= response.status_code < 300:
                    return FetchResult(
                        url=str(response.url),
                        status_code=response.status_code,
                        content=response.content,
                        content_type=response.headers.get("content-type"),
                    )

                if optional and response.status_code in OPTIONAL_STATUS:
                    return None

                if response.status_code not in RETRIABLE_STATUS:
                    if optional:
                        return None
                    raise FetchError(f"HTTP {response.status_code}: {url}")

                retry_after = response.headers.get("retry-after")
                delay = _retry_delay(attempt, retry_after)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = exc
                delay = min(0.5 * (2**attempt), 4.0)
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self._retries:
                    if optional:
                        return None
                    raise FetchError(f"request failed: {url}: {exc}") from exc
                delay = min(0.5 * (2**attempt), 4.0)

            if attempt < self._retries:
                await asyncio.sleep(delay)

        if optional:
            return None
        if last_error is not None:
            raise FetchError(f"request failed: {url}: {last_error}") from last_error
        raise FetchError(f"request failed: {url}")

    async def get_text(self, url: str) -> str:
        result = await self.get(url, optional=False)
        assert result is not None
        return result.content.decode("utf-8", errors="replace")


def _retry_delay(attempt: int, retry_after: str | None) -> float:
    if retry_after:
        try:
            return min(max(float(retry_after), 0.0), 30.0)
        except ValueError:
            pass
    return min(0.5 * (2**attempt), 4.0)
