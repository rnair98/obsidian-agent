"""Fitness: a configured filesystem backend is one the factory can build."""

from __future__ import annotations

from app.core.settings import FilesystemConfig
from app.engine.backends.factory import BACKEND_FACTORIES, FilesystemBackendType


def test_every_backend_type_is_registered_and_configured() -> None:
    missing = [
        kind.value for kind in FilesystemBackendType if kind not in BACKEND_FACTORIES
    ]
    assert missing == []
    assert FilesystemConfig().backend_type in BACKEND_FACTORIES
