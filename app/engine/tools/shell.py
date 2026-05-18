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
    """Run one exact allowlisted command in the agent workspace.

    Supported command forms are exactly: ``help [command]``, ``pwd``,
    ``cd [path]``, ``ls [path]``, ``cat path``, ``mkdir path``,
    ``write path content``, ``write path -- content``, ``rm path``,
    ``mv src dst``, ``cp src dst``, ``grep pattern path``,
    ``curl URL``, ``git ls-tree [-r] owner/repo``,
    ``git clone owner/repo [ref]``, ``python -c code``, and
    ``python path.py``. No other flags, pipelines, redirects, shell
    expansion, or host commands are supported. Run ``help`` or
    ``help <command>`` to inspect the grammar from inside the workspace.

    Args:
        command: One supported shell-like command form from the grammar above.

    Returns:
        The command's stdout, or stderr when the command fails.
    """
    return run_shell_command(command)
