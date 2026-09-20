from __future__ import annotations

import os
import sys
from typing import NoReturn

from packaging.version import InvalidVersion, Version
from project_version import read_project_version


def _fail(message: str) -> NoReturn:
    on_actions_runner = os.environ.get("GITHUB_ACTIONS") == "true"
    print(f"::error::{message}" if on_actions_runner else message, file=sys.stderr)
    raise SystemExit(1)


def _write_output(name: str, value: str) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        _fail("GITHUB_OUTPUT is not available")
    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"{name}={value}\n")


def main() -> None:
    try:
        version = read_project_version()
    except ValueError as exc:
        _fail(str(exc))
    tag = f"v{version}"
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    ref_type = os.environ.get("GITHUB_REF_TYPE", "")
    ref_name = os.environ.get("GITHUB_REF_NAME", "")

    if ref_type == "branch":
        if event != "workflow_dispatch" or ref_name != "main":
            _fail("Manual releases must be started from the main branch")
        mode = "prepare"
    elif ref_type == "tag":
        try:
            tag_version = Version(ref_name.removeprefix("v"))
        except InvalidVersion:
            _fail(f"Tag {ref_name!r} is not a valid version")
        if tag_version != Version(version):
            _fail(f"Tag {ref_name!r} does not match pyproject version {tag!r}")
        if ref_name != tag:
            _fail(f"Tag {ref_name!r} does not match the required form {tag!r}")
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
