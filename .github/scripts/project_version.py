from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read_project_version() -> str:
    """Read and validate project.version from the repository's pyproject.toml."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("pyproject.toml does not define a valid project.version")
    return version.strip()


def read_pyproject() -> dict[str, object]:
    """Load the repository's pyproject.toml as a plain dict."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)
