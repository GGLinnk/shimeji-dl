from pathlib import Path


def test_source_has_no_hardcoded_package_version() -> None:
    source = Path("src/shimeji_dl/version.py").read_text(encoding="utf-8")
    assert "__version__" not in source
    assert "importlib.metadata" in source
