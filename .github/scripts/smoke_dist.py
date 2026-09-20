from __future__ import annotations

import subprocess
from pathlib import Path

from project_version import ROOT, read_project_version

DIST = ROOT / "dist"


def only(pattern: str) -> Path:
    matches = sorted(DIST.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {pattern!r} in {DIST}, found {len(matches)}")
    return matches[0]


def smoke(package: Path, expected_version: str) -> None:
    completed = subprocess.run(
        [
            "uv",
            "run",
            "--isolated",
            "--no-project",
            "--with",
            str(package),
            "shimeji-dl",
            "--version",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    output = completed.stdout.strip()
    expected = f"shimeji-dl {expected_version}"
    if output != expected:
        raise RuntimeError(f"unexpected version output for {package.name}: {output!r}, expected {expected!r}")
    print(f"OK: {package.name} -> {output}")


def main() -> None:
    version = read_project_version()
    smoke(only("*.whl"), version)
    smoke(only("*.tar.gz"), version)


if __name__ == "__main__":
    main()
