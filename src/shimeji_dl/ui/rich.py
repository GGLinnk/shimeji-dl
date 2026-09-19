from __future__ import annotations

import sys
from collections.abc import Sequence

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TaskID, TextColumn
from rich.prompt import Confirm
from rich.table import Column

from ..core.models import CharacterRef, CharacterResult
from ..core.storage import compress_numbers


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

    def _make_progress(self) -> Progress:
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
        self._summary_task = self.progress.add_task("Progress", total=1, completed=1, phase="")
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
        self._completed += 1
        if result.failed:
            self._failed += 1
        self._sync_visible_tasks()
        self._update_summary()

    def report_results(self, results: Sequence[CharacterResult]) -> None:
        if self.quiet:
            return

        issues = [result for result in results if result.error or result.referenced_missing]
        if issues:
            self.progress.console.print(f"[bold]Issues:[/bold] {len(issues)} character(s)", overflow="fold")
            for result in issues:
                if result.error:
                    self.progress.console.print(
                        f"[red]error:[/red] {result.character.id}: {result.error}",
                        overflow="fold",
                    )
                for missing in result.referenced_missing:
                    self.warning(f"{result.character.id}: referenced-missing: {missing.path}")
                    if self.verbose_enabled:
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

    def warning(self, message: str) -> None:
        if not self.quiet:
            self.progress.console.print(f"[yellow]warning:[/yellow] {message}", overflow="fold")

    def info(self, message: str) -> None:
        if not self.quiet:
            self.progress.console.print(message, overflow="fold")

    def verbose(self, message: str) -> None:
        if self.verbose_enabled and not self.quiet:
            self.progress.console.print(f"[dim]{message}[/dim]", overflow="fold")

    def confirm(self, message: str, *, default: bool = False) -> bool:
        if not sys.stdin.isatty():
            return False
        return Confirm.ask(message, default=default, console=self.console)

    def finish(self) -> None:
        if self._started:
            self.progress.stop()
            self._started = False

    def fatal(self, message: str) -> None:
        self.error_console.print(f"[red]error:[/red] {message}", overflow="fold")

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
        queued = max(0, self._total - self._completed - len(self._active))
        hidden = max(0, len(self._active) - len(self._tasks))
        failed = f"[red]{self._failed} failed[/red]" if self._failed else "0 failed"
        parts = [
            f"{self._completed}/{self._total} done",
            f"{len(self._active)} active",
            f"{queued} queued",
            failed,
        ]
        if hidden:
            parts.append(f"{hidden} hidden")
        self.progress.update(self._summary_task, phase=" · ".join(parts))
