from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.engine.sandbox.models import ExecutionResult


@runtime_checkable
class ExecutionSandboxBackend(Protocol):
    """Port for sandboxed code execution.

    Implementers run untrusted code in an isolated environment and must
    enforce the provided timeout. Non-zero exit codes, captured stderr,
    and timeout events are all reported through the returned
    :class:`ExecutionResult` rather than raised.
    """

    def run_python(self, code: str, timeout_s: int) -> ExecutionResult:
        """Execute a snippet of Python in the sandbox.

        Args:
            code: Python source to run. Implementers must not mutate shared
                host state (filesystem, env, network) beyond what the
                sandbox policy permits.
            timeout_s: Maximum wall-clock seconds before the execution is
                terminated. Must be positive.

        Returns:
            An :class:`ExecutionResult` with stdout, stderr, exit code,
            and a ``timed_out`` flag.
        """
        ...
