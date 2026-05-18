from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from app.harness.paths import basename, normalize_path, parent_path

EntryKind = Literal["file", "directory"]


class WorkspaceBackendError(RuntimeError):
    """Base error for virtual workspace backend failures."""


class WorkspaceNotFoundError(WorkspaceBackendError):
    """Raised when a virtual path does not exist."""


class WorkspaceConflictError(WorkspaceBackendError):
    """Raised when an operation targets the wrong entry kind."""


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    path: str
    kind: EntryKind
    size: int = 0


@runtime_checkable
class WorkspaceBackend(Protocol):
    def exists(self, path: str) -> bool: ...

    def is_dir(self, path: str) -> bool: ...

    def list_dir(self, path: str) -> list[WorkspaceEntry]: ...

    def read_text(self, path: str) -> str: ...

    def write_text(self, path: str, content: str) -> None: ...

    def mkdir(self, path: str) -> None: ...

    def delete(self, path: str) -> None: ...

    def move(self, src: str, dst: str) -> None: ...


class InMemoryWorkspaceBackend:
    """Small deterministic in-memory filesystem for virtual workspace mounts."""

    def __init__(self) -> None:
        self._dirs: set[str] = {"/"}
        self._files: dict[str, str] = {}

    def exists(self, path: str) -> bool:
        normalized = normalize_path(path)
        return normalized in self._dirs or normalized in self._files

    def is_dir(self, path: str) -> bool:
        return normalize_path(path) in self._dirs

    def list_dir(self, path: str) -> list[WorkspaceEntry]:
        normalized = normalize_path(path)
        if normalized not in self._dirs:
            raise WorkspaceNotFoundError(f"directory not found: {path}")

        prefix = "/" if normalized == "/" else f"{normalized}/"
        entries: dict[str, WorkspaceEntry] = {}
        for directory in self._dirs:
            if directory == normalized or not directory.startswith(prefix):
                continue
            remainder = directory[len(prefix) :]
            if "/" not in remainder:
                entries[directory] = WorkspaceEntry(directory, "directory")
        for file_path, content in self._files.items():
            if not file_path.startswith(prefix):
                continue
            remainder = file_path[len(prefix) :]
            if "/" not in remainder:
                entries[file_path] = WorkspaceEntry(file_path, "file", len(content))
        return sorted(entries.values(), key=lambda entry: entry.path)

    def read_text(self, path: str) -> str:
        normalized = normalize_path(path)
        try:
            return self._files[normalized]
        except KeyError as exc:
            raise WorkspaceNotFoundError(f"file not found: {path}") from exc

    def write_text(self, path: str, content: str) -> None:
        normalized = normalize_path(path)
        parent = parent_path(normalized)
        self.mkdir(parent)
        if normalized in self._dirs:
            raise WorkspaceConflictError(f"cannot write directory: {path}")
        self._files[normalized] = content

    def mkdir(self, path: str) -> None:
        normalized = normalize_path(path)
        current = ""
        for part in normalized.split("/"):
            if not part:
                continue
            current = f"{current}/{part}"
            if current in self._files:
                raise WorkspaceConflictError(f"file blocks directory: {current}")
            self._dirs.add(current)

    def delete(self, path: str) -> None:
        normalized = normalize_path(path)
        if normalized == "/":
            raise WorkspaceConflictError("cannot delete mount root")
        if normalized in self._files:
            del self._files[normalized]
            return
        if normalized in self._dirs:
            prefix = f"{normalized}/"
            for file_path in list(self._files):
                if file_path.startswith(prefix):
                    del self._files[file_path]
            self._dirs = {
                directory
                for directory in self._dirs
                if directory == "/" or not directory.startswith(prefix)
            }
            self._dirs.discard(normalized)
            return
        raise WorkspaceNotFoundError(f"path not found: {path}")

    def move(self, src: str, dst: str) -> None:
        source = normalize_path(src)
        destination = normalize_path(dst)
        if source in self._files:
            content = self._files[source]
            del self._files[source]
            self.write_text(destination, content)
            return
        if source in self._dirs:
            if source == "/":
                raise WorkspaceConflictError("cannot move mount root")
            prefix = f"{source}/"
            moved_files = {
                file_path: content
                for file_path, content in self._files.items()
                if file_path.startswith(prefix)
            }
            self.mkdir(destination)
            for file_path in moved_files:
                relative = file_path[len(prefix) :]
                self.write_text(f"{destination}/{relative}", self._files[file_path])
            self.delete(source)
            return
        raise WorkspaceNotFoundError(f"path not found: {src}")

    def copy(self, src: str, dst: str) -> None:
        source = normalize_path(src)
        if source not in self._files:
            raise WorkspaceNotFoundError(f"file not found: {src}")
        self.write_text(dst, self._files[source])


def format_entries(entries: list[WorkspaceEntry]) -> str:
    return "".join(f"{basename(entry.path)}\n" for entry in entries)
