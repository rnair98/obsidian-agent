from __future__ import annotations

from app.engine.backends.protocol import FilesystemBackend
from app.engine.vaults import VaultLayout
from app.engine.workspace_commands.curl import CurlCommand
from app.engine.workspace_commands.git import GitCommand
from app.engine.workspace_commands.python import PythonCommand
from app.engine.workspace_commands.vault import VaultCommand
from app.harness.commands import WorkspaceCommand


def default_workspace_commands(
    vault: VaultLayout, assets: FilesystemBackend
) -> list[WorkspaceCommand]:
    return [
        CurlCommand(),
        GitCommand(),
        PythonCommand(),
        VaultCommand(vault, assets),
    ]


__all__ = [
    "CurlCommand",
    "GitCommand",
    "PythonCommand",
    "VaultCommand",
    "default_workspace_commands",
]
