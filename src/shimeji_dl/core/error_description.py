from __future__ import annotations


def describe_error(exc: BaseException) -> str:
    """Render an exception down to its leaf causes, however deeply grouped.

    Recurses into a BaseExceptionGroup instead of rendering it directly, since the group's own message never names the real failure.
    """
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(describe_error(sub) for sub in exc.exceptions)
    return f"{type(exc).__name__}: {exc}"
