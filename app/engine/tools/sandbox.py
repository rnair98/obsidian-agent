from langchain_core.tools import tool

from app.engine.sandbox import ExecutionResult, LocalSubprocessSandboxBackend

EXPERIMENT_ERROR_PREFIX = "Experiment error"
NO_OUTPUT_MESSAGE = "Experiment completed with no output."


def format_execution_result(result: ExecutionResult) -> str:
    if result.stderr:
        return f"{EXPERIMENT_ERROR_PREFIX}: {result.stderr}"
    return result.stdout or NO_OUTPUT_MESSAGE


@tool
def run_python_experiment(code: str) -> str:
    """
    Run a snippet of Python code in a sandbox (subprocess).
    Useful for verifying data processing or running small calculations.
    Returns the stdout of the execution.
    """
    result = LocalSubprocessSandboxBackend().run_python(code, timeout_s=10)
    return format_execution_result(result)
