from __future__ import annotations

from langchain.tools import tool

from app.harness.results import CommandResult
from app.harness.runtime import current_workspace


def _render_result(result: CommandResult) -> str:
    if result.stderr:
        return result.stderr
    return result.stdout


def run_shell_command(command: str) -> str:
    session = current_workspace()
    if session is None:
        return "No active workspace session. The shell tool is unavailable.\n"
    return _render_result(session.run(command))


@tool("shell", parse_docstring=True)
def shell(command: str) -> str:
    """Run an allowlisted command in the agent workspace.

    Supported commands include ``pwd``, ``cd``, ``ls``, ``cat``, ``mkdir``,
    ``write``, ``rm``, ``mv``, ``cp``, and ``grep``. The command is parsed by
    the workspace harness; it is not executed by the host shell.

    Args:
        command: Single allowlisted shell-like command to run.

    Returns:
        The command's stdout, or stderr when the command fails.
    """
    return run_shell_command(command)
