from __future__ import annotations

import shlex
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.harness.commands import (
    CommandSpec,
    WorkspaceCommand,
    first_flag,
    render_help,
    unsupported_flag,
)
from app.harness.fs import (
    InMemoryWorkspaceBackend,
    WorkspaceBackend,
    WorkspaceBackendError,
    format_entries,
)
from app.harness.mounts import CompositeWorkspaceBackend
from app.harness.paths import PathEscapeError, normalize_path
from app.harness.policy import PermissionPolicy, PolicyAction
from app.harness.results import AuditEvent, CommandResult

_UNSUPPORTED_TOKENS = {"|", "&&", "||", ";", ">", "<"}


@dataclass(frozen=True, slots=True)
class _SessionCommand:
    spec: CommandSpec
    method_name: str

    def __call__(self, session: "WorkspaceSession", args: list[str]) -> CommandResult:
        method = getattr(session, self.method_name)
        return method(args)


_CORE_COMMANDS: tuple[WorkspaceCommand, ...] = (
    _SessionCommand(CommandSpec(name="pwd", forms=("pwd",)), "_pwd"),
    _SessionCommand(CommandSpec(name="cd", forms=("cd [path]",)), "_cd"),
    _SessionCommand(CommandSpec(name="ls", forms=("ls [path]",)), "_ls"),
    _SessionCommand(CommandSpec(name="cat", forms=("cat path",)), "_cat"),
    _SessionCommand(CommandSpec(name="mkdir", forms=("mkdir path",)), "_mkdir"),
    _SessionCommand(
        CommandSpec(
            name="write",
            forms=("write path content", "write path -- content"),
        ),
        "_write",
    ),
    _SessionCommand(CommandSpec(name="rm", forms=("rm path",)), "_rm"),
    _SessionCommand(CommandSpec(name="mv", forms=("mv src dst",)), "_mv"),
    _SessionCommand(CommandSpec(name="cp", forms=("cp src dst",)), "_cp"),
    _SessionCommand(CommandSpec(name="grep", forms=("grep pattern path",)), "_grep"),
)


@dataclass(slots=True)
class WorkspaceSession:
    backend: CompositeWorkspaceBackend
    policy: PermissionPolicy
    cwd: str = "/workspace"
    commands: Mapping[str, WorkspaceCommand] = field(default_factory=dict)

    @classmethod
    def scratch(cls) -> "WorkspaceSession":
        return cls.with_mounts({"/workspace": InMemoryWorkspaceBackend()})

    @classmethod
    def with_mounts(
        cls,
        mounts: dict[str, WorkspaceBackend],
        *,
        policy: PermissionPolicy | None = None,
        cwd: str = "/workspace",
        commands: Iterable[WorkspaceCommand] = (),
    ) -> "WorkspaceSession":
        normalized_mounts = dict(mounts)
        if "/" not in normalized_mounts:
            normalized_mounts["/"] = (
                normalized_mounts.get("/workspace") or InMemoryWorkspaceBackend()
            )
        backend = CompositeWorkspaceBackend(
            normalized_mounts,
        )
        if "/workspace" in normalized_mounts:
            backend.mkdir("/workspace")
        return cls(
            backend=backend,
            policy=policy or PermissionPolicy.default(),
            cwd=normalize_path(cwd),
            commands=_command_map((*_CORE_COMMANDS, *commands)),
        )

    def run(self, command: str) -> CommandResult:
        try:
            args = shlex.split(command)
        except ValueError as exc:
            return CommandResult.error(f"{exc}\n", exit_code=2)
        if any(arg in _UNSUPPORTED_TOKENS for arg in args):
            return CommandResult.error(
                "unsupported shell syntax; run `help` for supported forms\n",
                exit_code=2,
            )
        if not args:
            return CommandResult.ok()

        command_name, *command_args = args
        try:
            if command_name == "help":
                return self._help(command_args)
            if registered := self.commands.get(command_name):
                return registered(self, command_args)
            return CommandResult.error(
                f"{command_name}: command not found\n", exit_code=127
            )
        except (PathEscapeError, WorkspaceBackendError, ValueError) as exc:
            return CommandResult.error(f"{exc}\n")

    def _pwd(self, args: list[str]) -> CommandResult:
        spec = self.commands["pwd"].spec
        if flag := first_flag(args):
            return unsupported_flag(spec, flag)
        return CommandResult.ok(f"{self.cwd}\n")

    def _cd(self, args: list[str]) -> CommandResult:
        spec = self.commands["cd"].spec
        if flag := first_flag(args):
            return unsupported_flag(spec, flag)
        if len(args) > 1:
            return CommandResult.error("cd: expected zero or one path\n", exit_code=2)
        target = self._resolve(args[0] if args else "/workspace")
        event = self._audit("read", target)
        if not event.allowed:
            return CommandResult.error("cd: permission denied\n", events=(event,))
        if not self.backend.is_dir(target):
            return CommandResult.error(f"cd: not a directory: {target}\n")
        self.cwd = target
        return CommandResult.ok(events=(event,))

    def _ls(self, args: list[str]) -> CommandResult:
        spec = self.commands["ls"].spec
        if flag := first_flag(args):
            return unsupported_flag(spec, flag)
        if len(args) > 1:
            return CommandResult.error("ls: expected zero or one path\n", exit_code=2)
        target = self._resolve(args[0] if args else ".")
        event = self._audit("read", target)
        if not event.allowed:
            return CommandResult.error("ls: permission denied\n", events=(event,))
        entries = self.backend.list_dir(target)
        return CommandResult.ok(format_entries(entries), events=(event,))

    def _cat(self, args: list[str]) -> CommandResult:
        spec = self.commands["cat"].spec
        if flag := first_flag(args):
            return unsupported_flag(spec, flag)
        if len(args) != 1:
            return CommandResult.error("cat: expected one path\n", exit_code=2)
        target = self._resolve(args[0])
        event = self._audit("read", target)
        if not event.allowed:
            return CommandResult.error("cat: permission denied\n", events=(event,))
        return CommandResult.ok(self.backend.read_text(target), events=(event,))

    def _mkdir(self, args: list[str]) -> CommandResult:
        spec = self.commands["mkdir"].spec
        if flag := first_flag(args):
            return unsupported_flag(spec, flag)
        if len(args) != 1:
            return CommandResult.error("mkdir: expected one path\n", exit_code=2)
        target = self._resolve(args[0])
        event = self._audit("write", target)
        if not event.allowed:
            return CommandResult.error("mkdir: permission denied\n", events=(event,))
        self.backend.mkdir(target)
        return CommandResult.ok(events=(event,))

    def _write(self, args: list[str]) -> CommandResult:
        if len(args) < 2:
            return CommandResult.error(
                "write: expected path and content\n", exit_code=2
            )
        if args[0].startswith("-"):
            return unsupported_flag(self.commands["write"].spec, args[0])
        target = self._resolve(args[0])
        event = self._audit("write", target)
        if not event.allowed:
            return CommandResult.error("write: permission denied\n", events=(event,))
        content_args = args[2:] if args[1] == "--" else args[1:]
        if not content_args and args[1] == "--":
            return CommandResult.error(
                "write: expected content after --\n", exit_code=2
            )
        self.backend.write_text(target, " ".join(content_args))
        return CommandResult.ok(events=(event,))

    def _rm(self, args: list[str]) -> CommandResult:
        spec = self.commands["rm"].spec
        if flag := first_flag(args):
            return unsupported_flag(spec, flag)
        if len(args) != 1:
            return CommandResult.error("rm: expected one path\n", exit_code=2)
        target = self._resolve(args[0])
        event = self._audit("delete", target)
        if not event.allowed:
            return CommandResult.error("rm: permission denied\n", events=(event,))
        self.backend.delete(target)
        return CommandResult.ok(events=(event,))

    def _mv(self, args: list[str]) -> CommandResult:
        spec = self.commands["mv"].spec
        if flag := first_flag(args):
            return unsupported_flag(spec, flag)
        if len(args) != 2:
            return CommandResult.error(
                "mv: expected source and destination\n", exit_code=2
            )
        src = self._resolve(args[0])
        dst = self._resolve(args[1])
        events = (self._audit("delete", src), self._audit("write", dst))
        if not all(event.allowed for event in events):
            return CommandResult.error("mv: permission denied\n", events=events)
        self.backend.move(src, dst)
        return CommandResult.ok(events=events)

    def _cp(self, args: list[str]) -> CommandResult:
        spec = self.commands["cp"].spec
        if flag := first_flag(args):
            return unsupported_flag(spec, flag)
        if len(args) != 2:
            return CommandResult.error(
                "cp: expected source and destination\n", exit_code=2
            )
        src = self._resolve(args[0])
        dst = self._resolve(args[1])
        events = (self._audit("read", src), self._audit("write", dst))
        if not all(event.allowed for event in events):
            return CommandResult.error("cp: permission denied\n", events=events)
        self.backend.copy(src, dst)
        return CommandResult.ok(events=events)

    def _grep(self, args: list[str]) -> CommandResult:
        spec = self.commands["grep"].spec
        if flag := first_flag(args):
            return unsupported_flag(spec, flag)
        if len(args) != 2:
            return CommandResult.error("grep: expected pattern and path\n", exit_code=2)
        pattern = args[0]
        target = self._resolve(args[1])
        event = self._audit("read", target)
        if not event.allowed:
            return CommandResult.error("grep: permission denied\n", events=(event,))
        lines = [
            line
            for line in self.backend.read_text(target).splitlines()
            if pattern in line
        ]
        return CommandResult.ok("".join(f"{line}\n" for line in lines), events=(event,))

    def _resolve(self, path: str) -> str:
        return normalize_path(path, cwd=self.cwd)

    def _audit(self, action: PolicyAction, path: str) -> AuditEvent:
        allowed = self.policy.allows(action, path)
        return AuditEvent(action=action, path=path, allowed=allowed)

    def _help(self, args: list[str]) -> CommandResult:
        if len(args) > 1:
            return CommandResult.error(
                "help: expected zero or one command\n",
                exit_code=2,
            )
        if not args:
            return CommandResult.ok(
                render_help([command.spec for command in self.commands.values()])
            )
        command = self.commands.get(args[0])
        if command is None:
            return CommandResult.error(
                f"help: unknown command: {args[0]}\n",
                exit_code=2,
            )
        return CommandResult.ok(f"{command.spec.help_text}\n")


def _command_map(commands: Iterable[WorkspaceCommand]) -> dict[str, WorkspaceCommand]:
    return {command.spec.name: command for command in commands}
