from __future__ import annotations

import json
import os
import sys

from project_version import read_pyproject

# Same predicate nox.project.python_versions uses for its classifiers path.
CLASSIFIER_PREFIX = "Programming Language :: Python :: 3."


def python_versions_from_classifiers() -> list[str]:
    pyproject = read_pyproject()
    classifiers = pyproject.get("project", {}).get("classifiers", [])
    return [classifier.split()[-1] for classifier in classifiers if classifier.startswith(CLASSIFIER_PREFIX)]


def main() -> None:
    versions = python_versions_from_classifiers()
    if not versions:
        print("::error::No Python version classifiers found in project.classifiers", file=sys.stderr)
        raise SystemExit(1)

    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        print("::error::GITHUB_OUTPUT is not available", file=sys.stderr)
        raise SystemExit(1)

    with open(output, "a", encoding="utf-8") as handle:
        handle.write(f"python-versions={json.dumps(versions)}\n")
    print(f"Python versions from classifiers: {versions}")


if __name__ == "__main__":
    main()
