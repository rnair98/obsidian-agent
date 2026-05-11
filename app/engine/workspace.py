from __future__ import annotations

from pathlib import Path

from app.core.settings import settings
from app.engine.artifacts import ArtifactWorkspaceBackend
from app.engine.backends import artifacts_backend, assets_backend
from app.engine.vaults import VaultLayout, ensure_vault_layout
from app.engine.workspace_commands import default_workspace_commands
from app.harness.fs import InMemoryWorkspaceBackend
from app.harness.policy import PermissionPolicy
from app.harness.session import WorkspaceSession


def build_workspace_session(vault: VaultLayout | None = None) -> WorkspaceSession:
    """Build the per-run agent workspace with durable artifact mounts."""
    artifact_backend = artifacts_backend()
    asset_backend = assets_backend()
    if vault is None:
        artifact_backend.mkdir(settings.MEMORIES_DIR)
        artifact_backend.mkdir(settings.OUTPUT_DIR)
        artifact_backend.mkdir(settings.VAULT_DIR)
        vault_backend = artifact_backend
        vault_root = settings.VAULT_DIR
        outputs_root = settings.OUTPUT_DIR
        memories_root = settings.MEMORIES_DIR
    else:
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
        cwd="/vault" if vault is not None else "/workspace",
        commands=default_workspace_commands(),
    )
