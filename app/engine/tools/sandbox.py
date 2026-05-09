import asyncio

from langchain_core.tools import tool

from app.engine.sandbox import ExecutionResult, LocalSubprocessSandboxBackend

EXPERIMENT_ERROR_PREFIX = "Experiment error"
NO_OUTPUT_MESSAGE = "Experiment completed with no output."


def format_execution_result(result: ExecutionResult) -> str:
    if result.stderr:
        return f"{EXPERIMENT_ERROR_PREFIX}: {result.stderr}"
    return result.stdout or NO_OUTPUT_MESSAGE


@tool(parse_docstring=True)
async def run_python_experiment(code: str) -> str:
    """Run a snippet of Python code in a sandboxed subprocess.

    Args:
        code: Python source to execute. Runs with a 10-second timeout.

    Returns:
        The captured stdout on success, a message prefixed with
        ``Experiment error:`` on failure, or a placeholder when stdout is
        empty.
    """
    backend = LocalSubprocessSandboxBackend()
    # Backend uses blocking ``subprocess.run`` — push it to a worker
    # thread so the event loop stays free for concurrent tool calls.
    result = await asyncio.to_thread(backend.run_python, code, 10)
    return format_execution_result(result)
