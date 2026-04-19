from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Callable

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
    # Normalize so ``"/x"`` and ``Path("/x")`` share one cache entry.
    key = str(Path(base_path).expanduser().resolve())
    return _cached_backend(backend_type, key)
