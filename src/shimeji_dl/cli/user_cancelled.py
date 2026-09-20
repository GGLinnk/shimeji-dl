from __future__ import annotations


class UserCancelled(RuntimeError):
    """The operator declined a confirmation prompt."""
