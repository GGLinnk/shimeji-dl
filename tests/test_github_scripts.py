from __future__ import annotations

import gzip
import importlib
import io
import json
import subprocess
import sys
import tarfile
import tomllib
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / ".github" / "scripts"


@pytest.fixture(autouse=True)
def _scripts_on_path() -> Iterator[None]:
    """Mirror how CI runs these scripts: their own directory goes on sys.path.

    Each script does a bare ``from project_version import ...``, which only resolves when the scripts directory (not the repository root) is importable.
    """
    sys.path.insert(0, str(SCRIPTS_DIR))
    try:
        yield
    finally:
        sys.path.remove(str(SCRIPTS_DIR))
        for name in ("project_version", "python_matrix", "release", "reproducible_build", "smoke_dist"):
            sys.modules.pop(name, None)


def _pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_read_project_version_matches_pyproject_literal() -> None:
    project_version = importlib.import_module("project_version")
    assert project_version.read_project_version() == _pyproject()["project"]["version"]


def test_read_project_version_calls_the_shared_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    """The version accessor must read through read_pyproject, its module's own loader.

    A stub loader here must be consulted, never silently bypassed by a second, independent read of pyproject.toml.
    """
    project_version = importlib.import_module("project_version")
    monkeypatch.setattr(project_version, "read_pyproject", lambda: {"project": {"version": "9.9.9"}})

    assert project_version.read_project_version() == "9.9.9"


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


def _run_node_harness(harness: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["node", "-e", harness],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_create_tag_and_dispatch_reports_an_existing_tag_as_a_typed_failure() -> None:
    """createRef's own refusal must be the single authority for tag absence.

    createRef's own 422 must surface as a typed, annotated failure through core.setFailed, with no separate pre-check racing the reference creation across two jobs.
    """
    release_path = SCRIPTS_DIR / "release.cjs"
    harness = f"""
    const release = require({json.dumps(str(release_path))});
    const failures = [];
    const core = {{ setFailed: (message) => failures.push(message), info: () => {{}} }};
    const conflict = new Error('Reference already exists');
    conflict.status = 422;
    const github = {{ rest: {{ git: {{ createRef: async () => {{ throw conflict; }} }} }} }};
    const context = {{ repo: {{ owner: 'o', repo: 'r' }}, sha: 'deadbeef' }};
    process.env.RELEASE_TAG = 'v1.2.3';
    release.createTagAndDispatch({{ github, context, core }}).then(() => {{
        if (failures.length !== 1) {{ console.error('expected exactly one failure, got ' + failures.length); process.exit(1); }}
        if (!failures[0].includes('already exists')) {{ console.error('unexpected message: ' + failures[0]); process.exit(1); }}
        process.exit(0);
    }}).catch((error) => {{ console.error(error); process.exit(1); }});
    """
    completed = _run_node_harness(harness)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_qualify_prepare_mode_never_pre_checks_tag_absence() -> None:
    """The qualify job must not race the tag creation with its own absence check.

    Its prepare-mode path must never call `git.getRef` to assert the tag is absent, since that check would run in a different job than the one that later creates the tag.
    """
    release_path = SCRIPTS_DIR / "release.cjs"
    harness = f"""
    const release = require({json.dumps(str(release_path))});
    const getRefCalls = [];
    const core = {{ setFailed: (message) => {{ throw new Error('unexpected failure: ' + message); }}, info: () => {{}}, setOutput: () => {{}} }};
    const github = {{
        rest: {{
            git: {{ getRef: async (args) => {{ getRefCalls.push(args); return {{ data: {{ object: {{ sha: 'deadbeef' }} }} }}; }} }},
            actions: {{ listWorkflowRuns: async () => [{{ id: 1, head_sha: 'deadbeef', head_branch: 'main', event: 'push', conclusion: 'success' }}], listWorkflowRunArtifacts: async () => [{{ id: 9, name: 'dist-deadbeef', expired: false }}] }},
        }},
        paginate: async (fn, args) => fn(args),
    }};
    const context = {{ repo: {{ owner: 'o', repo: 'r' }}, sha: 'deadbeef' }};
    process.env.RELEASE_MODE = 'prepare';
    process.env.RELEASE_TAG = 'v1.2.3';
    process.env.DIST_ARTIFACT_PREFIX = 'dist';
    release.qualify({{ github, context, core }}).then(() => {{
        const tagChecks = getRefCalls.filter((call) => String(call.ref).startsWith('tags/'));
        if (tagChecks.length !== 0) {{ console.error('unexpected tag-absence check: ' + JSON.stringify(tagChecks)); process.exit(1); }}
        process.exit(0);
    }}).catch((error) => {{ console.error(error); process.exit(1); }});
    """
    completed = _run_node_harness(harness)
    assert completed.returncode == 0, completed.stdout + completed.stderr


def _write_sdist(path: Path, *, gzip_mtime: int, member_mtime: int, member_name: str = "a.txt") -> None:
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as archive:
        data = b"content"
        info = tarfile.TarInfo(member_name)
        info.size = len(data)
        info.mtime = member_mtime
        archive.addfile(info, io.BytesIO(data))
    with path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=gzip_mtime) as gz:
        gz.write(tar_buffer.getvalue())


def test_compare_wheel_matches_identical_bytes(tmp_path: Path) -> None:
    reproducible_build = importlib.import_module("reproducible_build")
    first = tmp_path / "a.whl"
    second = tmp_path / "b.whl"
    first.write_bytes(b"identical content")
    second.write_bytes(b"identical content")

    result = reproducible_build.compare_wheel(first, second)

    assert result.reproducible
    assert "reproducible" in result.report()


def test_compare_wheel_flags_differing_bytes(tmp_path: Path) -> None:
    reproducible_build = importlib.import_module("reproducible_build")
    first = tmp_path / "a.whl"
    second = tmp_path / "b.whl"
    first.write_bytes(b"one version")
    second.write_bytes(b"a different version")

    result = reproducible_build.compare_wheel(first, second)

    assert not result.reproducible
    assert "NOT reproducible" in result.report()


def test_compare_sdist_reproducible_when_every_layer_matches(tmp_path: Path) -> None:
    reproducible_build = importlib.import_module("reproducible_build")
    first = tmp_path / "a.tar.gz"
    second = tmp_path / "b.tar.gz"
    _write_sdist(first, gzip_mtime=1000, member_mtime=1000)
    _write_sdist(second, gzip_mtime=1000, member_mtime=1000)

    result = reproducible_build.compare_sdist(first, second)

    assert result.reproducible
    assert result.sha256_matches
    assert result.gzip_header_mtime_matches
    assert result.mismatched_members == ()


def test_compare_sdist_reports_a_differing_gzip_header_mtime(tmp_path: Path) -> None:
    reproducible_build = importlib.import_module("reproducible_build")
    first = tmp_path / "a.tar.gz"
    second = tmp_path / "b.tar.gz"
    _write_sdist(first, gzip_mtime=1000, member_mtime=1000)
    _write_sdist(second, gzip_mtime=2000, member_mtime=1000)

    result = reproducible_build.compare_sdist(first, second)

    assert not result.reproducible
    assert result.gzip_header_mtime_matches is False
    assert "gzip header mtime differs" in result.report()


def test_compare_sdist_reports_which_member_mtime_differs(tmp_path: Path) -> None:
    reproducible_build = importlib.import_module("reproducible_build")
    first = tmp_path / "a.tar.gz"
    second = tmp_path / "b.tar.gz"
    _write_sdist(first, gzip_mtime=1000, member_mtime=1000, member_name="a.txt")
    _write_sdist(second, gzip_mtime=1000, member_mtime=9999, member_name="a.txt")

    result = reproducible_build.compare_sdist(first, second)

    assert not result.reproducible
    assert result.mismatched_members == ("a.txt",)
    assert "a.txt" in result.report()


def _write_pair(directory: Path, *, wheel_content: bytes, gzip_mtime: int, member_mtime: int) -> None:
    directory.mkdir()
    (directory / "pkg-1.0-py3-none-any.whl").write_bytes(wheel_content)
    _write_sdist(directory / "pkg-1.0.tar.gz", gzip_mtime=gzip_mtime, member_mtime=member_mtime)


def test_compare_all_includes_the_attested_dist_against_a_fresh_clone(tmp_path: Path) -> None:
    """compare_all must compare the attested dist/ against a fresh clone, not only clone against clone."""
    reproducible_build = importlib.import_module("reproducible_build")
    dist, first, second = tmp_path / "dist", tmp_path / "first", tmp_path / "second"
    for directory in (dist, first, second):
        _write_pair(directory, wheel_content=b"identical wheel", gzip_mtime=1000, member_mtime=1000)

    results = reproducible_build.compare_all(dist, first, second)

    assert len(results) == 4
    assert any("dist/" in label for label, _ in results)
    assert all(result.reproducible for _, result in results)


def test_compare_all_catches_a_dist_that_drifted_from_every_fresh_clone(tmp_path: Path) -> None:
    """A dist/ that drifted from a fresh rebuild must fail even when the two clones agree with each other."""
    reproducible_build = importlib.import_module("reproducible_build")
    dist, first, second = tmp_path / "dist", tmp_path / "first", tmp_path / "second"
    _write_pair(dist, wheel_content=b"a different wheel byte content", gzip_mtime=1000, member_mtime=1000)
    _write_pair(first, wheel_content=b"identical wheel", gzip_mtime=1000, member_mtime=1000)
    _write_pair(second, wheel_content=b"identical wheel", gzip_mtime=1000, member_mtime=1000)

    results = reproducible_build.compare_all(dist, first, second)

    clone_vs_clone = [result for label, result in results if "dist/" not in label]
    dist_vs_clone = [result for label, result in results if "dist/" in label]
    assert all(result.reproducible for result in clone_vs_clone)
    assert not all(result.reproducible for result in dist_vs_clone)
