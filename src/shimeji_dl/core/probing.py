from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterable

from .models import ProbeReport
from .probe_tuning import probe_tuning_for_mode

_NUMERIC_RE = re.compile(r"^shime([1-9][0-9]*)\.png$", re.IGNORECASE)

DEFAULT_PROBE_BATCH_SIZE = 64


def numeric_index(path: str) -> int | None:
    normalized = path.replace("\\", "/").lstrip("/")
    if "/" in normalized:
        return None
    match = _NUMERIC_RE.fullmatch(normalized)
    return int(match.group(1)) if match else None


def numeric_indices(paths: Iterable[str]) -> set[int]:
    return {index for path in paths if (index := numeric_index(path)) is not None}


def adaptive_quiet_span(hits: Iterable[int], mode: str, *, span_hint: int = 0) -> int:
    ordered = sorted(set(hits))
    largest_gap = max((right - left - 1 for left, right in zip(ordered, ordered[1:])), default=0)
    highest = ordered[-1] if ordered else 0
    bit_scale = max(1, highest.bit_length())
    tuning = probe_tuning_for_mode(mode)
    return max(
        tuning.base,
        (largest_gap + 1) * tuning.gap_factor,
        bit_scale * tuning.position_factor,
        span_hint * tuning.hint_factor,
    )


class AdaptiveNumericProber:
    """
    Generic adaptive explorer for a numeric namespace.  

    The callback owns the concrete naming and transport.  
    The algorithm only reasons about positive integer indices, making it reusable outside Shimeji sources.
    """

    def __init__(self, *, mode: str = "auto", batch_size: int = DEFAULT_PROBE_BATCH_SIZE) -> None:
        self.mode = mode
        self.batch_size = max(1, batch_size)

    async def run(
        self,
        probe: Callable[[int], Awaitable[bool]],
        *,
        anchors: Iterable[int] = (),
        known_hits: Iterable[int] = (),
    ) -> ProbeReport:
        report = ProbeReport(mode=self.mode, anchors=sorted(set(anchors)))
        if self.mode == "off":
            return report

        hits = set(known_hits)
        misses: set[int] = set()

        async def one(index: int, phase: str) -> bool:
            if index <= 0:
                return False
            if index in hits:
                return True
            if index in misses:
                return False
            report.requests += 1
            if phase == "gallop":
                report.gallop_probes += 1
            elif phase == "bisect":
                report.bisect_probes += 1
            elif phase == "fill":
                report.fill_probes += 1
            else:
                report.quiescence_probes += 1
            if await probe(index):
                hits.add(index)
                return True
            misses.add(index)
            return False

        async def probe_range(start: int, end: int, phase: str) -> bool:
            if end < start:
                return False
            before = set(hits)
            for cursor in range(start, end + 1, self.batch_size):
                batch_end = min(end, cursor + self.batch_size - 1)
                async with asyncio.TaskGroup() as group:
                    for index in range(cursor, batch_end + 1):
                        group.create_task(one(index, phase))
            return bool(hits - before)

        if not hits:
            await probe_range(1, probe_tuning_for_mode(self.mode).first_pass_span, "fill")
            if not hits:
                report.misses = sorted(misses)
                report.highest_tested = max(misses, default=None)
                report.stop_reason = "no-numeric-seed"
                return report

        await probe_range(1, max(hits), "fill")

        while hits:
            frontier = max(hits)
            offset = 1
            last_hit = frontier
            first_miss: int | None = None
            while True:
                candidate = frontier + offset
                if await one(candidate, "gallop"):
                    last_hit = candidate
                    offset *= 2
                    continue
                first_miss = candidate
                break

            span_hint = first_miss - frontier
            if last_hit > frontier:
                low, high = last_hit, first_miss
                while high - low > 1:
                    middle = (low + high) // 2
                    if await one(middle, "bisect"):
                        low = middle
                    else:
                        high = middle
                await probe_range(frontier + 1, low, "fill")
                frontier = max(hits)

            quiet = adaptive_quiet_span(hits, self.mode, span_hint=span_hint)
            report.quiescence_span = max(report.quiescence_span, quiet)
            quiet_end = frontier + quiet
            found_beyond = False
            for cursor in range(frontier + 1, quiet_end + 1, self.batch_size):
                batch_end = min(quiet_end, cursor + self.batch_size - 1)
                before_highest = max(hits)
                async with asyncio.TaskGroup() as group:
                    for index in range(cursor, batch_end + 1):
                        group.create_task(one(index, "quiescence"))
                if max(hits) > before_highest:
                    found_beyond = True
                    break
            if found_beyond:
                continue
            report.stop_reason = "quiescent-tail"
            break

        report.hits = sorted(hits)
        report.misses = sorted(misses)
        report.highest_hit = max(hits, default=None)
        report.highest_tested = max(hits | misses, default=None)
        return report
