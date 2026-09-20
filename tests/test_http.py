import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest
from tenacity import RetryCallState

from shimeji_dl.core.http import (
    MAX_RETRY_AFTER_SECONDS,
    HttpClient,
    _parse_retry_after,
    _wait_for_retry,
)
from shimeji_dl.core.http_error import HttpError
from shimeji_dl.core.retryable_http_error import RetryableHttpError


def _make_client() -> HttpClient:
    return HttpClient(connections=1, timeout=1.0, retries=2, user_agent="test-agent")


def _install_transport(client: HttpClient, handler) -> None:
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"User-Agent": "test-agent"})


def test_parse_retry_after_accepts_delay_seconds() -> None:
    assert _parse_retry_after("2") == 2.0


def test_parse_retry_after_accepts_http_date() -> None:
    future = datetime.now(timezone.utc) + timedelta(seconds=5)
    value = format_datetime(future, usegmt=True)
    parsed = _parse_retry_after(value)
    assert parsed is not None
    assert 4.0 <= parsed <= 6.0


def test_parse_retry_after_rejects_garbage() -> None:
    assert _parse_retry_after("not-a-date") is None
    assert _parse_retry_after(None) is None


def test_parse_retry_after_rejects_non_ascii_digit_without_raising() -> None:
    """A remote server controls this header; a non-ASCII digit that
    str.isdigit() admits but float() cannot convert must not raise."""
    assert _parse_retry_after("²") is None


class _FakeOutcome:
    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    def exception(self) -> BaseException:
        return self._exc


def test_wait_for_retry_honours_retry_after_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    state = RetryCallState(retry_object=None, fn=None, args=(), kwargs={})
    state.outcome = _FakeOutcome(RetryableHttpError("https://x", 429, MAX_RETRY_AFTER_SECONDS + 100))
    assert _wait_for_retry(state) == MAX_RETRY_AFTER_SECONDS


def test_wait_for_retry_falls_back_to_exponential_without_retry_after() -> None:
    state = RetryCallState(retry_object=None, fn=None, args=(), kwargs={})
    state.outcome = _FakeOutcome(RetryableHttpError("https://x", 503, None))
    wait = _wait_for_retry(state)
    assert 0.0 <= wait <= 4.0 + 1e-6


def test_get_retries_after_retry_after_header_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        recorded_sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", _fake_sleep)

    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, content=b"ok")

    client = _make_client()
    _install_transport(client, handler)

    result = asyncio.run(client.get("https://example/asset"))

    assert result is not None
    assert result.content == b"ok"
    assert calls["count"] == 2
    assert recorded_sleeps and recorded_sleeps[0] >= 2.0


def test_get_reraises_original_status_when_retries_exhausted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = HttpClient(connections=1, timeout=1.0, retries=0, user_agent="test-agent")
    _install_transport(client, handler)

    with pytest.raises(RetryableHttpError) as excinfo:
        asyncio.run(client.get("https://example/asset"))
    assert excinfo.value.status_code == 503


def test_get_wraps_transport_failure_without_status(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    client = HttpClient(connections=1, timeout=1.0, retries=0, user_agent="test-agent")
    _install_transport(client, handler)

    with pytest.raises(HttpError) as excinfo:
        asyncio.run(client.get("https://example/asset"))
    assert excinfo.value.status_code is None
    assert isinstance(excinfo.value.__cause__, httpx.ConnectError)


def test_get_text_decodes_declared_non_utf8_charset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content="café".encode("iso-8859-1"),
            headers={"content-type": "text/plain; charset=iso-8859-1"},
        )

    client = _make_client()
    _install_transport(client, handler)

    text = asyncio.run(client.get_text("https://example/page"))

    assert text == "café"


def test_get_text_wraps_invalid_bytes_for_declared_charset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"\xff\xfe\xfa",
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    client = _make_client()
    _install_transport(client, handler)

    with pytest.raises(HttpError):
        asyncio.run(client.get_text("https://example/page"))
