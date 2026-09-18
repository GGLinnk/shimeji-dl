from pathlib import Path


def test_generic_engine_has_no_concrete_source_or_ui_dependency() -> None:
    engine = Path("src/shimeji_dl/core/engine.py").read_text(encoding="utf-8")
    assert "shimejis.xyz" not in engine
    assert "ShimejisXYZ" not in engine
    assert "Rich" not in engine
    assert "lxml" not in engine
    assert "typer" not in engine


def test_rich_is_a_real_runtime_implementation() -> None:
    ui = Path("src/shimeji_dl/ui/rich.py").read_text(encoding="utf-8")
    assert "from rich.progress import Progress" in ui
    assert "self.progress.start()" in ui
