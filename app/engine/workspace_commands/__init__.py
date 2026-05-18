from __future__ import annotations

from app.engine.workspace_commands.curl import CurlCommand
from app.engine.workspace_commands.git import GitCommand
from app.engine.workspace_commands.python import PythonCommand
from app.harness.commands import WorkspaceCommand


def default_workspace_commands() -> list[WorkspaceCommand]:
    return [
        CurlCommand(),
        GitCommand(),
        PythonCommand(),
    ]


__all__ = [
    "CurlCommand",
    "GitCommand",
    "PythonCommand",
    "default_workspace_commands",
]
