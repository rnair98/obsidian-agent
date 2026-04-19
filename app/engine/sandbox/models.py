from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExecutionBackendType(StrEnum):
    LOCAL_SUBPROCESS = "local_subprocess"


@dataclass(slots=True)
class ExecutionResult:
    backend: ExecutionBackendType
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
