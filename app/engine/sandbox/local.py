from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

from app.engine.sandbox.models import ExecutionBackendType, ExecutionResult

TIMEOUT_EXIT_CODE = 124


@dataclass(slots=True)
class LocalSubprocessSandboxBackend:
    python_executable: str = sys.executable

    def run_python(self, code: str, timeout_s: int) -> ExecutionResult:
        try:
            process = subprocess.run(
                [self.python_executable, "-c", code],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "").strip()
            stderr = (exc.stderr or "").strip() or (
                f"Execution timed out after {timeout_s}s"
            )
            return ExecutionResult(
                backend=ExecutionBackendType.LOCAL_SUBPROCESS,
                exit_code=TIMEOUT_EXIT_CODE,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
            )

        return ExecutionResult(
            backend=ExecutionBackendType.LOCAL_SUBPROCESS,
            exit_code=process.returncode,
            stdout=process.stdout.strip(),
            stderr=process.stderr.strip(),
            timed_out=False,
        )
