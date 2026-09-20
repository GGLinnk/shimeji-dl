from pathlib import Path


def test_generic_engine_has_no_concrete_source_or_ui_dependency() -> None:
    engine = Path("src/shimeji_dl/core/engine.py").read_text(encoding="utf-8")
    assert "shimejis.xyz" not in engine
    assert "ShimejisXYZ" not in engine
    assert "Rich" not in engine
    assert "lxml" not in engine
    assert "typer" not in engine


def test_rich_is_a_real_runtime_implementation() -> None:
    from rich.progress import Progress

    from shimeji_dl.ui.rich import RichReporter

    reporter = RichReporter()
    assert isinstance(reporter.progress, Progress)
    ui = Path("src/shimeji_dl/ui/rich.py").read_text(encoding="utf-8")
    assert "self.progress.start()" in ui


def test_archive_package_has_no_network_adapter_dependency() -> None:
    for path in Path("src/shimeji_dl/archive").rglob("*.py"):
        content = path.read_text(encoding="utf-8")
        assert "shimejis_xyz.adapter" not in content, path
        assert "ShimejisXYZ" not in content, path
        assert "httpx" not in content, path
        assert "lxml" not in content, path
        assert "typer" not in content, path
