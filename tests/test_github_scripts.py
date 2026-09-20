from __future__ import annotations

import importlib
import json
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / ".github" / "scripts"


@pytest.fixture(autouse=True)
def _scripts_on_path() -> Iterator[None]:
    """Mirror how CI runs these scripts: their own directory goes on sys.path.

    Both modules do a bare ``from project_version import ...``, which only
    resolves when the scripts directory (not the repository root) is importable.
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        yield
    finally:
        sys.path.remove(str(SCRIPTS_DIR))
        for name in ("project_version", "python_matrix", "release"):
            sys.modules.pop(name, None)


def _pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_read_project_version_matches_pyproject_literal() -> None:
    project_version = importlib.import_module("project_version")
    assert project_version.read_project_version() == _pyproject()["project"]["version"]


def test_python_versions_from_classifiers_extracts_expected_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Feed a fixture classifier list and assert the exact expected output.

    Recomputing the expected value with the same filter-and-split expression
    the script itself uses would be unable to detect a shared defect in that
    expression; a fixture with edge cases (a bare major classifier, an
    "Only" qualifier, a non-Python classifier) and a hardcoded expectation
    is the only assertion that actually guards the parser.
    """
    python_matrix = importlib.import_module("python_matrix")
    prefix = python_matrix.CLASSIFIER_PREFIX
    fixture = {
        "project": {
            "classifiers": [
                "Development Status :: 4 - Beta",
                "Programming Language :: Python :: 3",
                "Programming Language :: Python :: 3 :: Only",
                f"{prefix}12",
                f"{prefix}13",
            ],
        },
    }
    monkeypatch.setattr(python_matrix, "read_pyproject", lambda: fixture)

    assert python_matrix.python_versions_from_classifiers() == ["3.12", "3.13"]


def test_python_matrix_main_writes_github_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_matrix = importlib.import_module("python_matrix")
    output_file = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))

    python_matrix.main()

    content = output_file.read_text(encoding="utf-8")
    assert content.startswith("python-versions=")
    written = json.loads(content.removeprefix("python-versions=").strip())
    assert written == python_matrix.python_versions_from_classifiers()


def _run_release_main(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    ref_type: str,
    ref_name: str,
    project_version: str = "1.2.3",
) -> Path:
    release = importlib.import_module("release")
    monkeypatch.setattr(release, "read_project_version", lambda: project_version)
    monkeypatch.setenv("GITHUB_REF_TYPE", ref_type)
    monkeypatch.setenv("GITHUB_REF_NAME", ref_name)
    output_file = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output_file))
    release.main()
    return output_file


def test_release_main_accepts_the_exact_required_tag_form(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    output_file = _run_release_main(monkeypatch, tmp_path, ref_type="tag", ref_name="v1.2.3")
    content = output_file.read_text(encoding="utf-8")
    assert "mode=publish\n" in content
    assert "tag=v1.2.3\n" in content


def test_release_main_rejects_a_tag_that_parses_equal_but_has_the_wrong_form(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A trailing zero component is value-equal to 1.2.3 under PEP 440.

    The version-aware comparison alone would accept it; the naming rule
    requires the exact string form, so this must still be rejected.
    """
    with pytest.raises(SystemExit):
        _run_release_main(monkeypatch, tmp_path, ref_type="tag", ref_name="v1.2.3.0")


def test_release_main_rejects_an_unparsable_tag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        _run_release_main(monkeypatch, tmp_path, ref_type="tag", ref_name="v-not-a-version")
    assert "is not a valid version" in capsys.readouterr().err
