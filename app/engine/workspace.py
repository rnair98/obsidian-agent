from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.settings import settings
from app.engine.backends import artifacts_backend
from app.engine.backends.protocol import FilesystemBackend
from app.harness.fs import (
    InMemoryWorkspaceBackend,
    WorkspaceBackendError,
    WorkspaceEntry,
    WorkspaceNotFoundError,
)
from app.harness.mounts import CompositeWorkspaceBackend
from app.harness.paths import normalize_path
from app.harness.policy import PermissionPolicy
from app.harness.session import WorkspaceSession


@dataclass(frozen=True, slots=True)
class FilesystemWorkspaceBackend:
    """Expose a FilesystemBackend subtree as a virtual workspace mount."""

    backend: FilesystemBackend
    root: Path

    def exists(self, path: str) -> bool:
        return self.backend.exists(self._artifact_path(path))

    def is_dir(self, path: str) -> bool:
        return self.backend.is_dir(self._artifact_path(path))

    def list_dir(self, path: str) -> list[WorkspaceEntry]:
        artifact_path = self._artifact_path(path)
        entries: list[WorkspaceEntry] = []
        root = self.backend.resolve(self.root)
        for child in self.backend.list_dir(artifact_path):
            relative = child.relative_to(root).as_posix()
            virtual_path = normalize_path(f"/{relative}")
            kind = "directory" if child.is_dir() else "file"
            size = child.stat().st_size if child.is_file() else 0
            entries.append(WorkspaceEntry(virtual_path, kind, size))
        return entries

    def read_text(self, path: str) -> str:
        target = self._artifact_path(path)
        if not self.backend.is_file(target):
            raise WorkspaceNotFoundError(f"file not found: {path}")
        return self.backend.read_text(target)

    def write_text(self, path: str, content: str) -> None:
        self.backend.write_text(self._artifact_path(path), content)

    def mkdir(self, path: str) -> None:
        self.backend.mkdir(self._artifact_path(path))

    def delete(self, path: str) -> None:
        target = self._artifact_path(path)
        if self._is_mount_root(path):
            raise WorkspaceBackendError("cannot delete mount root")
        if self.backend.is_dir(target):
            self.backend.delete_dir(target, missing_ok=False)
            return
        if self.backend.is_file(target):
            self.backend.delete_file(target, missing_ok=False)
            return
        raise WorkspaceNotFoundError(f"path not found: {path}")

    def move(self, src: str, dst: str) -> None:
        if self._is_mount_root(src):
            raise WorkspaceBackendError("cannot move mount root")
        self.backend.move(self._artifact_path(src), self._artifact_path(dst))

    def copy(self, src: str, dst: str) -> None:
        self.write_text(dst, self.read_text(src))

    def _artifact_path(self, path: str) -> Path:
        normalized = normalize_path(path)
        if normalized == "/":
            return self.root
        return self.root / normalized.removeprefix("/")

    @staticmethod
    def _is_mount_root(path: str) -> bool:
        return normalize_path(path) == "/"


def build_workspace_session() -> WorkspaceSession:
    """Build the per-run agent workspace with durable artifact mounts."""
    artifact_backend = artifacts_backend()
    artifact_backend.mkdir(settings.MEMORIES_DIR)
    artifact_backend.mkdir(settings.VAULT_DIR)

    workspace = InMemoryWorkspaceBackend()
    repos = InMemoryWorkspaceBackend()
    backend = CompositeWorkspaceBackend(
        {
            "/": workspace,
            "/workspace": workspace,
            "/memory": FilesystemWorkspaceBackend(
                artifact_backend,
                settings.MEMORIES_DIR,
            ),
            "/vault": FilesystemWorkspaceBackend(
                artifact_backend,
                settings.VAULT_DIR,
            ),
            "/repos": repos,
        }
    )
    backend.mkdir("/workspace")
    backend.mkdir("/repos")
    return WorkspaceSession(backend=backend, policy=PermissionPolicy.default())
