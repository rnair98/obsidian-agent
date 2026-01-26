import subprocess
import sys

from langchain_core.tools import tool


@tool
def run_python_experiment(code: str) -> str:
    """
    Run a snippet of Python code in a sandbox (subprocess).
    Useful for verifying data processing or running small calculations.
    Returns the stdout of the execution.
    """
    timeout = 10
    process = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    stdout = process.stdout.strip()
    stderr = process.stderr.strip()
    if stderr:
        return f"Experiment error: {stderr}"
    return stdout or "Experiment completed with no output."
