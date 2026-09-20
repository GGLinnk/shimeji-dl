from __future__ import annotations

from pathlib import Path


def image_output_root(output: Path) -> Path:
    """Resolve the `img/` directory an output root implies.

    If the supplied output directory is itself already named `img`, it is used directly instead of creating a redundant nested `img/img`.
    """
    return output if output.name.casefold() == "img" else output / "img"
