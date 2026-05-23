from __future__ import annotations

from pathlib import Path

from app.engine.artifacts import ArtifactWorkspaceBackend
from app.engine.backends.protocol import FilesystemBackend
from app.engine.vaults import VaultLayout, ensure_vault_layout
from app.engine.workspace_commands import default_workspace_commands
from app.harness.fs import InMemoryWorkspaceBackend
from app.harness.policy import PermissionPolicy
from app.harness.session import WorkspaceSession


def build_workspace_session(
    asset_backend: FilesystemBackend,
    vault: VaultLayout,
) -> WorkspaceSession:
    """Build the per-run agent workspace with durable artifact mounts."""
    vault = ensure_vault_layout(vault)
    vault_backend = vault.backend
    vault_root = vault.root
    outputs_root = vault.outputs_dir
    memories_root = vault.memories_dir

    return WorkspaceSession.with_mounts(
        {
            "/workspace": InMemoryWorkspaceBackend(),
            "/outputs": ArtifactWorkspaceBackend(
                vault_backend,
                outputs_root,
            ),
            "/memory": ArtifactWorkspaceBackend(
                vault_backend,
                memories_root,
            ),
            "/vault": ArtifactWorkspaceBackend(
                vault_backend,
                vault_root,
            ),
            "/repos": ArtifactWorkspaceBackend(asset_backend, Path(".")),
        },
        policy=PermissionPolicy.default(),
        cwd="/vault",
        commands=default_workspace_commands(),
    )
