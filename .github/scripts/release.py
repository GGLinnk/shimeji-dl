from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path


def _fail(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def _project_version() -> str:
    with Path("pyproject.toml").open("rb") as handle:
        data = tomllib.load(handle)
    version = data.get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        _fail("pyproject.toml does not define a valid project.version")
    return version.strip()


def _write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        _fail("GITHUB_OUTPUT is not available")
    with Path(output).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> None:
    version = _project_version()
    tag = f"v{version}"
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    ref_type = os.environ.get("GITHUB_REF_TYPE", "")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")

    if ref_type == "branch":
        if event != "workflow_dispatch" or ref_name != "main":
            _fail("Manual releases must be started from the main branch")
        mode = "prepare"
    elif ref_type == "tag":
        if ref_name != tag:
            _fail(f"Tag {ref_name!r} does not match pyproject version {tag!r}")
        mode = "publish"
    else:
        _fail(f"Unsupported release ref type: {ref_type!r}")

    _write_output("mode", mode)
    _write_output("version", version)
    _write_output("tag", tag)
    print(f"Release mode: {mode}")
    print(f"Version: {version}")
    print(f"Tag: {tag}")


if __name__ == "__main__":
    main()
