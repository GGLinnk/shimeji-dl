from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "dist"


def only(directory: Path, pattern: str) -> Path:
    """Resolve exactly one match of a glob pattern in a directory, or fail loudly."""
    matches = sorted(directory.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {pattern!r} in {directory}, found {len(matches)}")
    return matches[0]


def read_pyproject() -> dict[str, object]:
    """Load the repository's pyproject.toml as a plain dict."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def read_project_version() -> str:
    """Read and validate project.version from the repository's pyproject.toml."""
    data = read_pyproject()
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("pyproject.toml does not define a valid project.version")
    return version.strip()
