from __future__ import annotations

import shlex
from dataclasses import dataclass

from app.harness.fs import (
    InMemoryWorkspaceBackend,
    WorkspaceBackendError,
    format_entries,
)
from app.harness.mounts import CompositeWorkspaceBackend
from app.harness.paths import PathEscapeError, normalize_path
from app.harness.policy import PermissionPolicy, PolicyAction
from app.harness.results import AuditEvent, CommandResult

_UNSUPPORTED_TOKENS = ("|", "&&", "||", ";", "$(", "`", ">", "<")


@dataclass(slots=True)
class WorkspaceSession:
    backend: CompositeWorkspaceBackend
    policy: PermissionPolicy
    cwd: str = "/workspace"

    @classmethod
    def default(cls) -> "WorkspaceSession":
        workspace = InMemoryWorkspaceBackend()
        backend = CompositeWorkspaceBackend(
            {
                "/": workspace,
                "/workspace": workspace,
            }
        )
        backend.mkdir("/workspace")
        return cls(backend=backend, policy=PermissionPolicy.default())

    def run(self, command: str) -> CommandResult:
        if any(token in command for token in _UNSUPPORTED_TOKENS):
            return CommandResult.error("unsupported shell syntax\n", exit_code=2)
        try:
            args = shlex.split(command)
        except ValueError as exc:
            return CommandResult.error(f"{exc}\n", exit_code=2)
        if not args:
            return CommandResult.ok()

        command_name, *command_args = args
        try:
            match command_name:
                case "pwd":
                    return CommandResult.ok(f"{self.cwd}\n")
                case "cd":
                    return self._cd(command_args)
                case "ls":
                    return self._ls(command_args)
                case "cat":
                    return self._cat(command_args)
                case "mkdir":
                    return self._mkdir(command_args)
                case "write":
                    return self._write(command_args)
                case "rm":
                    return self._rm(command_args)
                case "mv":
                    return self._mv(command_args)
                case "cp":
                    return self._cp(command_args)
                case "grep":
                    return self._grep(command_args)
                case "git":
                    return CommandResult.error(
                        "git facade is not implemented yet\n", exit_code=2
                    )
                case _:
                    return CommandResult.error(
                        f"{command_name}: command not found\n", exit_code=127
                    )
        except (PathEscapeError, WorkspaceBackendError, ValueError) as exc:
            return CommandResult.error(f"{exc}\n")

    def _cd(self, args: list[str]) -> CommandResult:
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
        if len(args) > 1:
            return CommandResult.error("ls: expected zero or one path\n", exit_code=2)
        target = self._resolve(args[0] if args else ".")
        event = self._audit("read", target)
        if not event.allowed:
            return CommandResult.error("ls: permission denied\n", events=(event,))
        entries = self.backend.list_dir(target)
        return CommandResult.ok(format_entries(entries), events=(event,))

    def _cat(self, args: list[str]) -> CommandResult:
        if len(args) != 1:
            return CommandResult.error("cat: expected one path\n", exit_code=2)
        target = self._resolve(args[0])
        event = self._audit("read", target)
        if not event.allowed:
            return CommandResult.error("cat: permission denied\n", events=(event,))
        return CommandResult.ok(self.backend.read_text(target), events=(event,))

    def _mkdir(self, args: list[str]) -> CommandResult:
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
        target = self._resolve(args[0])
        event = self._audit("write", target)
        if not event.allowed:
            return CommandResult.error("write: permission denied\n", events=(event,))
        self.backend.write_text(target, " ".join(args[1:]))
        return CommandResult.ok(events=(event,))

    def _rm(self, args: list[str]) -> CommandResult:
        if len(args) != 1:
            return CommandResult.error("rm: expected one path\n", exit_code=2)
        target = self._resolve(args[0])
        event = self._audit("delete", target)
        if not event.allowed:
            return CommandResult.error("rm: permission denied\n", events=(event,))
        self.backend.delete(target)
        return CommandResult.ok(events=(event,))

    def _mv(self, args: list[str]) -> CommandResult:
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
