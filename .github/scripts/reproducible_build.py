from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from project_version import DIST, ROOT, only

# RFC 1952 gzip header: this code reads the 4-byte little-endian MTIME field at byte offset 4.
_GZIP_HEADER_LENGTH = 10
_GZIP_MTIME_OFFSET = 4
_GZIP_MTIME_LENGTH = 4


@dataclass(frozen=True, slots=True)
class ArtifactReproducibility:
    """One artifact's byte-reproducibility across two independent builds, by layer."""

    name: str
    sha256_matches: bool
    gzip_header_mtime_matches: bool | None
    mismatched_members: tuple[str, ...]

    @property
    def reproducible(self) -> bool:
        return self.sha256_matches and self.gzip_header_mtime_matches is not False and not self.mismatched_members

    def report(self) -> str:
        if self.reproducible:
            return f"{self.name}: reproducible"
        layers = [f"outer sha256 {'matches' if self.sha256_matches else 'differs'}"]
        if self.gzip_header_mtime_matches is not None:
            layers.append(f"gzip header mtime {'matches' if self.gzip_header_mtime_matches else 'differs'}")
        if self.mismatched_members:
            layers.append(f"{len(self.mismatched_members)} tar member mtime(s) differ: {', '.join(self.mismatched_members)}")
        return f"{self.name}: NOT reproducible ({'; '.join(layers)})"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _gzip_header_mtime(path: Path) -> int:
    with path.open("rb") as handle:
        header = handle.read(_GZIP_HEADER_LENGTH)
    start = _GZIP_MTIME_OFFSET
    return int.from_bytes(header[start : start + _GZIP_MTIME_LENGTH], "little")


def _tar_member_mtimes(path: Path) -> dict[str, int]:
    with tarfile.open(path, "r:gz") as archive:
        return {member.name: member.mtime for member in archive.getmembers()}


def compare_wheel(first: Path, second: Path) -> ArtifactReproducibility:
    return ArtifactReproducibility(first.name, _sha256(first) == _sha256(second), None, ())


def compare_sdist(first: Path, second: Path) -> ArtifactReproducibility:
    sha_matches = _sha256(first) == _sha256(second)
    gzip_matches = _gzip_header_mtime(first) == _gzip_header_mtime(second)
    first_members = _tar_member_mtimes(first)
    second_members = _tar_member_mtimes(second)
    mismatched = tuple(
        sorted(
            name
            for name in first_members.keys() | second_members.keys()
            if first_members.get(name) != second_members.get(name)
        )
    )
    return ArtifactReproducibility(first.name, sha_matches, gzip_matches, mismatched)


def _current_commit() -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _clone_and_build(commit: str, destination: Path) -> Path:
    """Check out the exact commit into a fresh clone and build it there.

    A fresh clone (never a rebuild of the same checkout) is required: git stamps each checked-out file with the wall-clock time of that checkout, the same source of non-determinism SOURCE_DATE_EPOCH is meant to replace, so only two genuinely separate checkouts can expose a backend that silently falls back to it.
    """
    subprocess.run(
        ["git", "clone", "--no-hardlinks", "--quiet", str(ROOT), str(destination)],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(destination), "checkout", "--quiet", commit],
        check=True,
    )
    epoch = subprocess.run(
        ["git", "-C", str(destination), "log", "-1", "--format=%ct"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["uv", "build"],
        cwd=destination,
        check=True,
        env={**os.environ, "SOURCE_DATE_EPOCH": epoch},
    )
    return destination / DIST.name


def compare_all(dist: Path, first_dist: Path, second_dist: Path) -> list[tuple[str, ArtifactReproducibility]]:
    """Compare the attested dist/ against a fresh clone, then that clone against a second one.

    The first pair is the check that matters: `dist/` is what the earlier Build step produced and what `actions/attest` signs, so a byte difference there means the attestation covers bytes nobody can rebuild.
    The second pair rules out a fluke tied to one particular clone.
    """
    return [
        ("attested dist/ vs fresh clone (wheel)", compare_wheel(only(dist, "*.whl"), only(first_dist, "*.whl"))),
        ("attested dist/ vs fresh clone (sdist)", compare_sdist(only(dist, "*.tar.gz"), only(first_dist, "*.tar.gz"))),
        ("fresh clone vs fresh clone (wheel)", compare_wheel(only(first_dist, "*.whl"), only(second_dist, "*.whl"))),
        ("fresh clone vs fresh clone (sdist)", compare_sdist(only(first_dist, "*.tar.gz"), only(second_dist, "*.tar.gz"))),
    ]


def main() -> None:
    commit = _current_commit()
    with tempfile.TemporaryDirectory(prefix="shimeji-dl-reproducibility-") as workdir:
        first_dist = _clone_and_build(commit, Path(workdir) / "first")
        second_dist = _clone_and_build(commit, Path(workdir) / "second")
        results = compare_all(DIST, first_dist, second_dist)

    for label, result in results:
        print(f"{label}: {result.report()}")

    if not all(result.reproducible for _, result in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
