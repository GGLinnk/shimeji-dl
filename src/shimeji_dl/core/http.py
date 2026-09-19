from __future__ import annotations

from dataclasses import dataclass

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

RETRIABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
OPTIONAL_STATUS = {400, 401, 403, 404, 405, 410}


@dataclass(frozen=True, slots=True)
class HttpResult:
    url: str
    status_code: int
    content: bytes
    content_type: str | None


class HttpError(RuntimeError):
    pass


class RetryableHttpError(HttpError):
    pass


class HttpClient:
    """Bounded asynchronous HTTP client with reusable retry policy."""

    def __init__(
        self,
        *,
        connections: int,
        timeout: float,
        retries: int,
        user_agent: str,
    ) -> None:
        self._retries = max(0, retries)
        limits = httpx.Limits(max_connections=connections, max_keepalive_connections=connections)
        self._client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(timeout),
            limits=limits,
            headers={"User-Agent": user_agent, "Accept": "*/*"},
        )

    async def __aenter__(self) -> "HttpClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get(
        self,
        url: str,
        *,
        optional: bool = False,
        headers: dict[str, str] | None = None,
    ) -> HttpResult | None:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._retries + 1),
                wait=wait_random_exponential(multiplier=0.5, max=4.0),
                retry=retry_if_exception_type(
                    (httpx.TimeoutException, httpx.NetworkError, RetryableHttpError)
                ),
                reraise=True,
            ):
                with attempt:
                    response = await self._client.get(url, headers=headers)

                    if 200 <= response.status_code < 300:
                        return HttpResult(
                            url=str(response.url),
                            status_code=response.status_code,
                            content=response.content,
                            content_type=response.headers.get("content-type"),
                        )
                    if optional and response.status_code in OPTIONAL_STATUS:
                        return None
                    if response.status_code in RETRIABLE_STATUS:
                        raise RetryableHttpError(f"HTTP {response.status_code}: {url}")
                    if optional:
                        return None
                    raise HttpError(f"HTTP {response.status_code}: {url}")
        except (httpx.HTTPError, RetryableHttpError) as exc:
            if optional:
                return None
            raise HttpError(f"request failed: {url}: {exc}") from exc

        return None

    async def get_text(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        result = await self.get(url, optional=False, headers=headers)
        if result is None:
            raise HttpError(f"request returned no result: {url}")
        return result.content.decode("utf-8", errors="replace")
