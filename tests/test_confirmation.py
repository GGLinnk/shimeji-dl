from __future__ import annotations

from shimeji_dl.core.confirmation import Confirmation, ask_for_confirmation


class _ReporterStub:
    def __init__(self, *, can_confirm: bool = True, answer: bool = True, raises_eof: bool = False) -> None:
        self.messages: list[str] = []
        self._can_confirm = can_confirm
        self._answer = answer
        self._raises_eof = raises_eof

    def can_confirm(self) -> bool:
        return self._can_confirm

    def confirm(self, message: str, *, default: bool = False) -> bool:
        self.messages.append(message)
        if self._raises_eof:
            raise EOFError("stdin closed while reading the confirmation")
        return self._answer


def test_ask_for_confirmation_returns_accepted_on_a_yes_answer() -> None:
    reporter = _ReporterStub(answer=True)

    assert ask_for_confirmation(reporter, "Proceed?") is Confirmation.ACCEPTED
    assert reporter.messages == ["Proceed?"]


def test_ask_for_confirmation_returns_declined_on_a_no_answer() -> None:
    reporter = _ReporterStub(answer=False)

    assert ask_for_confirmation(reporter, "Proceed?") is Confirmation.DECLINED


def test_ask_for_confirmation_returns_unavailable_when_the_reporter_cannot_confirm() -> None:
    reporter = _ReporterStub(can_confirm=False)

    assert ask_for_confirmation(reporter, "Proceed?") is Confirmation.UNAVAILABLE
    assert reporter.messages == []


def test_ask_for_confirmation_returns_unavailable_when_the_prompt_hits_eof() -> None:
    """A terminal reported as interactive but closed mid-read must never crash bare."""
    reporter = _ReporterStub(can_confirm=True, raises_eof=True)

    assert ask_for_confirmation(reporter, "Proceed?") is Confirmation.UNAVAILABLE
