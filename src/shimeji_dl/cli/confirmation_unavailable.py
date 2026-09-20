from __future__ import annotations


class ConfirmationUnavailable(RuntimeError):
    """No interactive terminal could answer a confirmation this target required."""

    def __init__(self, target: str) -> None:
        super().__init__(f"no confirmation could be asked for {target}: no interactive terminal")
        self.target = target
