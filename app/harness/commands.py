from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from app.harness.results import CommandResult

if TYPE_CHECKING:
    from app.harness.session import WorkspaceSession


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    forms: tuple[str, ...]

    @property
    def help_text(self) -> str:
        return "\n".join(self.forms)

    @property
    def first_form(self) -> str:
        return self.forms[0]


class WorkspaceCommand(Protocol):
    spec: CommandSpec

    def __call__(
        self,
        session: WorkspaceSession,
        args: list[str],
    ) -> CommandResult: ...


def first_flag(args: list[str]) -> str | None:
    return next((arg for arg in args if arg.startswith("-") and arg != "--"), None)


def unsupported_flag(spec: CommandSpec, flag: str) -> CommandResult:
    return CommandResult.error(
        f"{spec.name}: unsupported flag: {flag}; supported form: {spec.first_form}\n",
        exit_code=2,
    )


def render_help(command_specs: list[CommandSpec]) -> str:
    return (
        "Supported command forms:\n"
        + "\n".join(spec.help_text for spec in command_specs)
        + "\n\nNo other flags, pipelines, redirects, shell expansion, "
        "or host commands are supported.\n"
    )
