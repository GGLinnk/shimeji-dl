from __future__ import annotations


def describe_error(exc: BaseException) -> str:
    """Render an exception down to its leaf causes.

    ``asyncio.TaskGroup`` wraps sibling failures in a ``BaseExceptionGroup``, and a
    ``TaskGroup`` nested inside another ``TaskGroup`` (as with a per-target extraction
    task nested inside the overall extraction task group) nests one group inside
    another. Rendering the group itself collapses to the unhelpful
    "ExceptionGroup: unhandled errors in a TaskGroup (N sub-exceptions)"; this instead
    recurses to the actual leaf exceptions and joins their messages.
    """
    if isinstance(exc, BaseExceptionGroup):
        return "; ".join(describe_error(sub) for sub in exc.exceptions)
    return f"{type(exc).__name__}: {exc}"
