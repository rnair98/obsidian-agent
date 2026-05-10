from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from app.core.paths import DEFAULT_ASSETS_DIR
from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.backends.protocol import FilesystemBackend


class FilesystemBackendType(StrEnum):
    IN_PROCESS = "inprocess"


BackendFactory = Callable[[str | Path], FilesystemBackend]

BACKEND_FACTORIES: dict[FilesystemBackendType, BackendFactory] = {
    FilesystemBackendType.IN_PROCESS: InProcessFilesystemBackend,
}


@lru_cache(maxsize=8)
def _cached_backend(
    backend_type: FilesystemBackendType,
    base_path_key: str,
) -> FilesystemBackend:
    return BACKEND_FACTORIES[backend_type](base_path_key)


def get_filesystem_backend(
    backend_type: FilesystemBackendType = FilesystemBackendType.IN_PROCESS,
    base_path: str | Path = DEFAULT_ASSETS_DIR,
) -> FilesystemBackend:
    """Resolve a backend by ``(type, base_path)``.

    Prefer the named accessors :func:`artifacts_backend` /
    :func:`assets_backend` for the two well-known sandboxes — they make
    the load-bearing separation between agent artifacts (`.memories`,
    `.vault`, `outputs`) and GitHub snapshots (``.assets/<owner>/...``)
    explicit at the call site.
    """
    # Normalize so ``"/x"`` and ``Path("/x")`` share one cache entry.
    key = str(Path(base_path).expanduser().resolve())
    return _cached_backend(backend_type, key)


def artifacts_backend() -> FilesystemBackend:
    """Backend rooted at ``settings.filesystem.base_path`` (agent artifacts)."""
    from app.core.settings import settings

    return get_filesystem_backend(
        backend_type=settings.filesystem.backend_type,
        base_path=settings.filesystem.base_path,
    )


def assets_backend() -> FilesystemBackend:
    """Backend rooted at ``DEFAULT_ASSETS_DIR`` (GitHub snapshots)."""
    return get_filesystem_backend(base_path=DEFAULT_ASSETS_DIR)
