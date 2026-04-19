from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.engine.sandbox.models import ExecutionResult


@runtime_checkable
class ExecutionSandboxBackend(Protocol):
    def run_python(self, code: str, timeout_s: int) -> ExecutionResult: ...
