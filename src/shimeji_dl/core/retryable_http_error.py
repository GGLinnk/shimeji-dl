from __future__ import annotations

from .http_error import HttpError


class RetryableHttpError(HttpError):
    """Raised for an HTTP failure the caller's retry policy should retry."""

    def __init__(
        self,
        url: str,
        status_code: int | None,
        retry_after: float | None,
        message: str | None = None,
    ) -> None:
        super().__init__(url, status_code, message)
        self.retry_after = retry_after
