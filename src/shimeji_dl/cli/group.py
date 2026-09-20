from __future__ import annotations

from typer._click import Context
from typer.core import TyperGroup


class DefaultCommandGroup(TyperGroup):
    """Typer command group that defaults to the download command.

    The first argument is read as an implicit `download` target whenever it names neither a known subcommand nor one of the group's own options (its long or short form, including a secondary opt of a flag pair), so an existing single-command invocation keeps working once a second command exists.
    A target named exactly like a command still resolves to that command; the documented fallback is to name `download` explicitly.
    """

    default_command = "download"

    def parse_args(self, ctx: Context, args: list[str]) -> list[str]:
        if args:
            head = args[0].split("=", 1)[0]
            group_option_names = {
                name
                for param in self.get_params(ctx)
                for name in (*param.opts, *param.secondary_opts)
            }
            if head not in self.commands and head not in group_option_names:
                args = [self.default_command, *args]
        return super().parse_args(ctx, args)
