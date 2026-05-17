from __future__ import annotations

from app.harness.fs import WorkspaceBackend, WorkspaceBackendError, WorkspaceEntry
from app.harness.paths import normalize_path


class CompositeWorkspaceBackend:
    """Route virtual paths to mounted backends by longest prefix."""

    def __init__(self, mounts: dict[str, WorkspaceBackend]) -> None:
        if "/" not in mounts:
            raise ValueError("composite workspace requires a root mount")
        self._mounts = {
            normalize_path(prefix): backend for prefix, backend in mounts.items()
        }

    def exists(self, path: str) -> bool:
        backend, backend_path = self._route(path)
        return backend.exists(backend_path)

    def is_dir(self, path: str) -> bool:
        backend, backend_path = self._route(path)
        return backend.is_dir(backend_path)

    def list_dir(self, path: str) -> list[WorkspaceEntry]:
        normalized = normalize_path(path)
        backend, backend_path = self._route(normalized)
        entries = self._prefix_entries(
            mount_prefix=self._route_prefix(normalized),
            entries=backend.list_dir(backend_path),
        )

        mounted_children = [
            WorkspaceEntry(prefix, "directory")
            for prefix in self._mounts
            if prefix != "/" and self._parent(prefix) == normalized
        ]
        # Mounted children win over root-backend entries at the same path so
        # we never report `/vault` twice when the root backend also has a
        # `vault/` directory.
        merged: dict[str, WorkspaceEntry] = {entry.path: entry for entry in entries}
        for child in mounted_children:
            merged[child.path] = child
        return sorted(merged.values(), key=lambda entry: entry.path)

    def read_text(self, path: str) -> str:
        backend, backend_path = self._route(path)
        return backend.read_text(backend_path)

    def write_text(self, path: str, content: str) -> None:
        backend, backend_path = self._route(path)
        backend.write_text(backend_path, content)

    def mkdir(self, path: str) -> None:
        backend, backend_path = self._route(path)
        backend.mkdir(backend_path)

    def delete(self, path: str) -> None:
        backend, backend_path = self._route(path)
        backend.delete(backend_path)

    def move(self, src: str, dst: str) -> None:
        src_backend, src_path = self._route(src)
        dst_backend, dst_path = self._route(dst)
        if src_backend is not dst_backend:
            if src_backend.is_dir(src_path):
                raise WorkspaceBackendError(
                    "cross-mount move of directories is not supported"
                )
            content = src_backend.read_text(src_path)
            dst_backend.write_text(dst_path, content)
            src_backend.delete(src_path)
            return
        src_backend.move(src_path, dst_path)

    def copy(self, src: str, dst: str) -> None:
        content = self.read_text(src)
        self.write_text(dst, content)

    def _route(self, path: str) -> tuple[WorkspaceBackend, str]:
        normalized = normalize_path(path)
        prefix = self._route_prefix(normalized)
        backend = self._mounts[prefix]
        if prefix == "/":
            return backend, normalized
        if normalized == prefix:
            return backend, "/"
        return backend, normalized.removeprefix(prefix)

    def _route_prefix(self, path: str) -> str:
        normalized = normalize_path(path)
        candidates = sorted(self._mounts, key=len, reverse=True)
        for prefix in candidates:
            if prefix == "/":
                continue
            if normalized == prefix or normalized.startswith(f"{prefix}/"):
                return prefix
        return "/"

    @staticmethod
    def _parent(path: str) -> str:
        if path == "/":
            return "/"
        parent = path.rsplit("/", maxsplit=1)[0]
        return parent or "/"

    @staticmethod
    def _prefix_entries(
        *,
        mount_prefix: str,
        entries: list[WorkspaceEntry],
    ) -> list[WorkspaceEntry]:
        if mount_prefix == "/":
            return entries
        return [
            WorkspaceEntry(f"{mount_prefix}{entry.path}", entry.kind, entry.size)
            for entry in entries
        ]
