from __future__ import annotations


class HttpError(RuntimeError):
    """Raised when an HTTP request fails without a retryable outcome."""

    def __init__(self, url: str, status_code: int | None, message: str | None = None) -> None:
        super().__init__(message or f"HTTP request failed: {url}")
        self.url = url
        self.status_code = status_code
