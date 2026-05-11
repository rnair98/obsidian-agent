from __future__ import annotations

from app.core.settings import settings
from app.engine.artifacts import ArtifactWorkspaceBackend
from app.engine.backends import artifacts_backend
from app.harness.fs import InMemoryWorkspaceBackend
from app.harness.policy import PermissionPolicy
from app.harness.session import WorkspaceSession


def build_workspace_session() -> WorkspaceSession:
    """Build the per-run agent workspace with durable artifact mounts."""
    artifact_backend = artifacts_backend()
    artifact_backend.mkdir(settings.MEMORIES_DIR)
    artifact_backend.mkdir(settings.VAULT_DIR)

    return WorkspaceSession.with_mounts(
        {
            "/workspace": InMemoryWorkspaceBackend(),
            "/memory": ArtifactWorkspaceBackend(
                artifact_backend,
                settings.MEMORIES_DIR,
            ),
            "/vault": ArtifactWorkspaceBackend(
                artifact_backend,
                settings.VAULT_DIR,
            ),
            "/repos": InMemoryWorkspaceBackend(),
        },
        policy=PermissionPolicy.default(),
    )
