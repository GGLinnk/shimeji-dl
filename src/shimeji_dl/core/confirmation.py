from __future__ import annotations

from enum import Enum
from typing import Protocol


class ConfirmingReporter(Protocol):
    """The minimal confirmation surface `ask_for_confirmation` needs from any reporter."""

    def confirm(self, message: str, *, default: bool = False) -> bool: ...

    def can_confirm(self) -> bool: ...


class Confirmation(Enum):
    """The outcome of asking once: accepted, declined, or not askable at all."""

    ACCEPTED = "accepted"
    DECLINED = "declined"
    UNAVAILABLE = "unavailable"


def ask_for_confirmation(reporter: ConfirmingReporter, message: str, *, default: bool = False) -> Confirmation:
    """Ask once; the one owner every confirmation call site defers to.

    A reporter that cannot confirm at all, and a terminal that reports as interactive but yields no answer (`EOFError` from the prompt itself), both become `UNAVAILABLE`: never a bare crash, never a duplicated try/except at each call site.
    """
    if not reporter.can_confirm():
        return Confirmation.UNAVAILABLE
    try:
        answered_yes = reporter.confirm(message, default=default)
    except EOFError:
        return Confirmation.UNAVAILABLE
    return Confirmation.ACCEPTED if answered_yes else Confirmation.DECLINED
