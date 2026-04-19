from __future__ import annotations

from typing import Protocol

from app.engine.sandbox.models import ExecutionResult


class ExecutionSandboxBackend(Protocol):
    def run_python(self, code: str, timeout_s: int) -> ExecutionResult: ...
