from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AuditAction = Literal["read", "write", "delete"]


@dataclass(frozen=True, slots=True)
class AuditEvent:
    action: AuditAction
    path: str
    allowed: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    events: tuple[AuditEvent, ...] = field(default_factory=tuple)

    @classmethod
    def ok(
        cls, stdout: str = "", events: tuple[AuditEvent, ...] = ()
    ) -> "CommandResult":
        return cls(stdout=stdout, exit_code=0, events=events)

    @classmethod
    def error(
        cls,
        stderr: str,
        *,
        exit_code: int = 1,
        events: tuple[AuditEvent, ...] = (),
    ) -> "CommandResult":
        return cls(stderr=stderr, exit_code=exit_code, events=events)
