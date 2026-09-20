from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProbeTuning:
    """Tuning knobs for the adaptive numeric prober's quiescence heuristic."""

    # Floor of the quiescence span, in indices, regardless of the other terms.
    base: int
    # Multiplies the largest gap seen between two hits.
    gap_factor: int
    # Multiplies the highest hit's bit length, so the span scales with magnitude.
    position_factor: int
    # Multiplies the gallop-to-bisect overshoot from the last frontier probe.
    hint_factor: int
    # Width of the very first probe range, before any hit is known.
    first_pass_span: int


DEEP_PROBE_TUNING = ProbeTuning(base=128, gap_factor=8, position_factor=8, hint_factor=2, first_pass_span=32)
AUTO_PROBE_TUNING = ProbeTuning(base=32, gap_factor=4, position_factor=4, hint_factor=1, first_pass_span=8)


def probe_tuning_for_mode(mode: str) -> ProbeTuning:
    return DEEP_PROBE_TUNING if mode == "deep" else AUTO_PROBE_TUNING
