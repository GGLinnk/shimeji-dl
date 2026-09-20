from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from .http_error import HttpError
from .retryable_http_error import RetryableHttpError

RETRIABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}
OPTIONAL_STATUS = {400, 401, 403, 404, 405, 410}

DEFAULT_TEXT_ENCODING = "utf-8"

# Exponential backoff base, seconds, used when a retryable response
# carries no usable Retry-After header.
RETRY_WAIT_MULTIPLIER_SECONDS = 0.5
# Upper bound of the exponential backoff, seconds.
RETRY_WAIT_MAX_SECONDS = 4.0
# Upper bound honoured from a server-supplied Retry-After header, so a
# misbehaving or hostile server cannot stall a run indefinitely.
MAX_RETRY_AFTER_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class HttpResult:
    url: str
    status_code: int
    content: bytes
    content_type: str | None
    encoding: str | None


def _parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header per RFC 9110: delay-seconds or an HTTP-date.

    RFC 9110's delay-seconds is ASCII digits only; str.isdigit() also admits
    non-ASCII decimal digits (and some digit-like characters) that float()
    cannot convert, so the ASCII check must gate the numeric branch too.
    """
    if value is None:
        return None
    stripped = value.strip()
    if stripped.isascii() and stripped.isdigit():
        return float(stripped)
    try:
        target = parsedate_to_datetime(stripped)
    except (TypeError, ValueError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


def _wait_for_retry(retry_state: RetryCallState) -> float:
    outcome = retry_state.outcome
    exc = outcome.exception() if outcome is not None else None
    if isinstance(exc, RetryableHttpError) and exc.retry_after is not None:
        return min(exc.retry_after, MAX_RETRY_AFTER_SECONDS)
    fallback = wait_random_exponential(multiplier=RETRY_WAIT_MULTIPLIER_SECONDS, max=RETRY_WAIT_MAX_SECONDS)
    return fallback(retry_state)


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
                wait=_wait_for_retry,
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
                            encoding=response.encoding,
                        )
                    if optional and response.status_code in OPTIONAL_STATUS:
                        return None
                    if response.status_code in RETRIABLE_STATUS:
                        raise RetryableHttpError(
                            url,
                            response.status_code,
                            _parse_retry_after(response.headers.get("retry-after")),
                            f"HTTP {response.status_code}: {url}",
                        )
                    if optional:
                        return None
                    raise HttpError(url, response.status_code, f"HTTP {response.status_code}: {url}")
        except RetryableHttpError:
            if optional:
                return None
            raise
        except httpx.HTTPError as exc:
            if optional:
                return None
            raise HttpError(url, None, f"request failed: {url}: {exc}") from exc

        return None

    async def get_text(self, url: str, *, headers: dict[str, str] | None = None) -> str:
        result = await self.get(url, optional=False, headers=headers)
        if result is None:
            raise HttpError(url, None, f"request returned no result: {url}")
        encoding = result.encoding or DEFAULT_TEXT_ENCODING
        try:
            return result.content.decode(encoding)
        except UnicodeDecodeError as exc:
            raise HttpError(
                url,
                result.status_code,
                f"could not decode response as {encoding}: {url}",
            ) from exc
