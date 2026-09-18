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
        self._started = False

    def _make_progress(self) -> Progress:
        return Progress(
            SpinnerColumn(table_column=Column(width=1, no_wrap=True)),
            TextColumn(
                "{task.description} [dim]{task.fields[phase]}[/dim]",
                table_column=Column(ratio=1, no_wrap=False, overflow="fold"),
            ),
            console=self.console,
            transient=False,
            expand=True,
        )

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
        self.progress.start()
        self._started = True
        for character in characters:
            self._tasks[character.id] = self.progress.add_task(character.id, total=None, phase="Queued")

    def character_started(self, character: CharacterRef) -> None:
        self.character_phase(character, "Starting")

    def character_phase(self, character: CharacterRef, phase: str, detail: str = "") -> None:
        if self.quiet:
            return
        task = self._tasks.get(character.id)
        if task is not None:
            suffix = f" · {detail}" if detail else ""
            self.progress.update(task, phase=f"{phase}{suffix}")

    def character_finished(self, result: CharacterResult) -> None:
        if self.quiet:
            return
        task = self._tasks.get(result.character.id)
        if result.error:
            details = f"[red]failed[/red] · {result.error}"
        else:
            config_labels = [name for name, config in result.configs.items() if config]
            details = f"{len(result.asset_paths)} sprite(s)"
            if config_labels:
                details += " · " + ", ".join(config_labels)
            if result.referenced_missing:
                details += f" · [yellow]{len(result.referenced_missing)} missing[/yellow]"
        if task is not None:
            self.progress.update(task, phase=details, completed=1, total=1)
            self.progress.stop_task(task)

        for missing in result.referenced_missing:
            self.warning(f"{result.character.id}: referenced-missing: {missing.path}")
            if self.verbose_enabled:
                for url in missing.tried_urls:
                    self.verbose(f"tried: {url}")
        if self.verbose_enabled and result.probe.mode != "off":
            self.verbose(
                f"{result.character.id}: probe hits={len(result.probe.hits)}, "
                f"extras={len(result.probe.extra_hits)}, tested={result.probe.requests}, "
                f"highest={result.probe.highest_tested}, stop={result.probe.stop_reason}"
            )
            if result.probe.misses:
                self.verbose(f"{result.character.id}: probe-missing: {', '.join(compress_numbers(result.probe.misses))}")

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
