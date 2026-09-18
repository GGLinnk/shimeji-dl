from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_PACKAGE_NAME = "shimeji-dl"


def get_version() -> str:
    """Return the installed package version.

    ``pyproject.toml`` is the single source of truth. No version number is
    duplicated in the Python sources.
    """
    try:
        return version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return "0+unknown"
