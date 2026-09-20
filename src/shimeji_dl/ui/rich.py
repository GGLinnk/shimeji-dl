from __future__ import annotations

import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TextColumn
from rich.prompt import Confirm
from rich.table import Column

from ..core.models import CharacterRef, CharacterResult
from ..core.storage import compress_numbers

# Binary unit step for rendering an archive's size in the outcome line.
_BYTES_PER_UNIT = 1024
_SIZE_UNITS = ("B", "KiB", "MiB", "GiB", "TiB")


def _human_size(size: int) -> str:
    value = float(size)
    for unit in _SIZE_UNITS[:-1]:
        if value < _BYTES_PER_UNIT:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= _BYTES_PER_UNIT
    return f"{value:.1f} {_SIZE_UNITS[-1]}"


class RichReporter:
    def __init__(
        self,
        *,
        quiet: bool = False,
        verbose: bool = False,
        console: Console | None = None,
        error_console: Console | None = None,
    ) -> None:
        self.quiet = quiet
        self.verbose_enabled = verbose
        self.console = console or Console(stderr=False)
        self.error_console = error_console or Console(stderr=True)
        self.progress = self._make_progress()
        self._tasks: dict[str, TaskID] = {}
        self._active: dict[str, str] = {}
        self._summary_task: TaskID | None = None
        self._total = 0
        self._completed = 0
        self._failed = 0
        self._visible_capacity = 1
        self._started = False
        self._archive_progress: Progress | None = None
        self._archive_task: TaskID | None = None

    def _make_progress(self) -> Progress:
        # No BarColumn or MofNCompleteColumn: every column here is
        # shared with the per-character rows, and a fixed-width column
        # would steal space a long character name needs to fold instead
        # of ellipsizing.  The completed count is reported as text.
        progress = Progress(
            SpinnerColumn(table_column=Column(width=1, no_wrap=True)),
            TextColumn(
                "{task.description} [dim]{task.fields[phase]}[/dim]",
                table_column=Column(ratio=1, no_wrap=False, overflow="fold"),
            ),
            console=self.console,
            transient=False,
            expand=True,
        )
        progress.live.vertical_overflow = "visible"
        return progress

    def extraction(self, source: str, target: str) -> None:
        if not self.quiet:
            self.console.print(f"[cyan]extractor[/cyan][dim][{source}][/dim]: {target}", overflow="fold")

    def start(self, characters: Sequence[CharacterRef]) -> None:
        if self.quiet:
            return
        if self._started:
            self.finish()
        self.progress = self._make_progress()
        self._tasks.clear()
        self._active.clear()
        self._total = len(characters)
        self._completed = 0
        self._failed = 0
        self._visible_capacity = max(1, self.console.height - 3)
        self.progress.start()
        self._started = True
        self._summary_task = self.progress.add_task("Progress", total=self._total, completed=0, phase="")
        self._update_summary()

    def character_started(self, character: CharacterRef) -> None:
        if self.quiet:
            return
        self._active[character.id] = "Starting"
        self._sync_visible_tasks()
        self._update_summary()

    def character_phase(self, character: CharacterRef, phase: str, detail: str = "") -> None:
        if self.quiet:
            return
        suffix = f" · {detail}" if detail else ""
        phase_text = f"{phase}{suffix}"
        self._active[character.id] = phase_text
        task = self._tasks.get(character.id)
        if task is not None:
            self.progress.update(task, phase=phase_text)
        else:
            self._sync_visible_tasks()

    def character_finished(self, result: CharacterResult) -> None:
        if self.quiet:
            return
        self._active.pop(result.character.id, None)
        task = self._tasks.pop(result.character.id, None)
        if task is not None:
            self.progress.remove_task(task)
        if result.retryable:
            self._failed += 1
        self._completed += 1
        if self._summary_task is not None:
            self.progress.advance(self._summary_task, 1)
        self._sync_visible_tasks()
        self._update_summary()

    def report_results(self, results: Sequence[CharacterResult], *, output: Path) -> None:
        issues = [result for result in results if result.error or result.referenced_missing]
        if issues:
            self.progress.console.print(f"[bold]Issues:[/bold] {len(issues)} character(s)", overflow="fold")
            for result in issues:
                if result.error:
                    self.progress.console.print(
                        f"[red]error:[/red] {escape(result.character.id)}: {escape(result.error)}",
                        overflow="fold",
                    )
                missing_counts = Counter(item.kind for item in result.referenced_missing)
                for kind, count in sorted(missing_counts.items()):
                    self.warning(f"{result.character.id}: {count} {kind} asset(s)")
                if self.verbose_enabled:
                    for missing in result.referenced_missing:
                        self.verbose(f"{result.character.id}: {missing.kind}: {missing.path}")
                        for url in missing.tried_urls:
                            self.verbose(f"tried: {url}")

        if self.verbose_enabled:
            for result in results:
                if result.probe.mode == "off":
                    continue
                self.verbose(
                    f"{result.character.id}: probe hits={len(result.probe.hits)}, "
                    f"extras={len(result.probe.extra_hits)}, tested={result.probe.requests}, "
                    f"highest={result.probe.highest_tested}, stop={result.probe.stop_reason}"
                )
                if result.probe.misses:
                    self.verbose(
                        f"{result.character.id}: probe-missing: {', '.join(compress_numbers(result.probe.misses))}"
                    )

        usable = sum(result.usable for result in results)
        complete = sum(result.complete for result in results)
        source_missing = sum(
            any(item.kind == "source-missing" for item in result.referenced_missing) for result in results
        )
        unusable = len(results) - usable
        self.progress.console.print(
            f"Finished: {usable}/{len(results)} usable, {complete}/{len(results)} complete, "
            f"{source_missing} source-missing, {unusable} unusable character(s). "
            f"Output: {output}",
            overflow="fold",
        )

    def warning(self, message: str) -> None:
        # Quiet suppresses progress and informational output only; a warning is neither and always prints.
        self.progress.console.print(f"[yellow]warning:[/yellow] {escape(message)}", overflow="fold")

    def info(self, message: str) -> None:
        if not self.quiet:
            self.progress.console.print(escape(message), overflow="fold")

    def verbose(self, message: str) -> None:
        if self.verbose_enabled and not self.quiet:
            self.progress.console.print(f"[dim]{escape(message)}[/dim]", overflow="fold")

    def can_confirm(self) -> bool:
        if sys.stdin is None or sys.stdin.closed:
            return False
        try:
            return sys.stdin.isatty()
        except OSError:
            return False

    def confirm(self, message: str, *, default: bool = False) -> bool:
        if not self.can_confirm():
            return False
        return Confirm.ask(escape(message), default=default, console=self.console)

    def finish(self) -> None:
        if self._started:
            self.progress.stop()
            self._started = False

    def fatal(self, message: str) -> None:
        self.error_console.print(f"[red]error:[/red] {escape(message)}", overflow="fold")

    def archive_started(self, name: str, entry_count: int, byte_total: int) -> None:
        # The announcement always prints, even under --quiet: only the progress bar respects it.
        self.console.print(f"[cyan]archive[/cyan]: {escape(name)} ({entry_count} entries)", overflow="fold")
        if self.quiet:
            return
        self._archive_progress = Progress(
            SpinnerColumn(table_column=Column(width=1, no_wrap=True)),
            TextColumn("{task.description}", table_column=Column(ratio=1, no_wrap=False, overflow="fold")),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            console=self.console,
            transient=True,
        )
        self._archive_progress.start()
        self._archive_task = self._archive_progress.add_task(name, total=entry_count)

    def archive_entry_written(self, entries_done: int, entry_count: int) -> None:
        if self._archive_progress is not None and self._archive_task is not None:
            self._archive_progress.update(self._archive_task, completed=entries_done)

    def archive_finished(self, path: Path, entry_count: int, size: int) -> None:
        if self._archive_progress is not None:
            self._archive_progress.stop()
            self._archive_progress = None
            self._archive_task = None
        # The outcome always prints, even under --quiet.
        self.console.print(f"[cyan]archive[/cyan]: {escape(str(path))} ({_human_size(size)})", overflow="fold")

    def _sync_visible_tasks(self) -> None:
        for character_id, task in list(self._tasks.items()):
            if character_id not in self._active:
                self.progress.remove_task(task)
                del self._tasks[character_id]

        for character_id, phase in self._active.items():
            if character_id in self._tasks:
                continue
            if len(self._tasks) >= self._visible_capacity:
                break
            self._tasks[character_id] = self.progress.add_task(character_id, total=None, phase=phase)

    def _update_summary(self) -> None:
        if self._summary_task is None:
            return
        completed = self._completed
        queued = max(0, self._total - completed - len(self._active))
        hidden = max(0, len(self._active) - len(self._tasks))
        failed = f"[red]{self._failed} failed[/red]" if self._failed else "0 failed"
        parts = [
            f"{completed}/{self._total} done",
            f"{len(self._active)} active",
            f"{queued} queued",
            failed,
        ]
        if hidden:
            parts.append(f"{hidden} hidden")
        self.progress.update(self._summary_task, phase=" · ".join(parts))
