from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from app.harness.session import WorkspaceSession

_CURRENT_WORKSPACE: ContextVar[WorkspaceSession | None] = ContextVar(
    "current_workspace",
    default=None,
)


def current_workspace() -> WorkspaceSession | None:
    return _CURRENT_WORKSPACE.get()


@contextmanager
def workspace_scope(session: WorkspaceSession) -> Generator[WorkspaceSession]:
    token = _CURRENT_WORKSPACE.set(session)
    try:
        yield session
    finally:
        _CURRENT_WORKSPACE.reset(token)
