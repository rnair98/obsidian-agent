from __future__ import annotations

from app.engine.sandbox.local import LocalSubprocessSandboxBackend
from app.engine.sandbox.models import ExecutionBackendType, ExecutionResult
from app.engine.tools.sandbox import (
    EXPERIMENT_ERROR_PREFIX,
    NO_OUTPUT_MESSAGE,
    format_execution_result,
)


def test_local_subprocess_backend_captures_stdout() -> None:
    backend = LocalSubprocessSandboxBackend(python_executable="python3")

    result = backend.run_python("print('hello')", timeout_s=5)

    assert isinstance(result, ExecutionResult)
    assert result.backend == ExecutionBackendType.LOCAL_SUBPROCESS
    assert result.exit_code == 0
    assert result.stdout == "hello"
    assert result.stderr == ""
    assert result.timed_out is False


def test_format_execution_result_prefers_stderr_for_failures() -> None:
    result = ExecutionResult(
        backend=ExecutionBackendType.LOCAL_SUBPROCESS,
        exit_code=1,
        stdout="",
        stderr="boom",
        timed_out=False,
    )

    assert format_execution_result(result) == f"{EXPERIMENT_ERROR_PREFIX}: boom"


def test_format_execution_result_handles_empty_success_output() -> None:
    result = ExecutionResult(
        backend=ExecutionBackendType.LOCAL_SUBPROCESS,
        exit_code=0,
        stdout="",
        stderr="",
        timed_out=False,
    )

    assert format_execution_result(result) == NO_OUTPUT_MESSAGE
