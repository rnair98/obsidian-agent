from __future__ import annotations

from app.engine.tools.shell import run_shell_command
from app.harness.runtime import workspace_scope
from app.harness.session import WorkspaceSession


def test_shell_adapter_uses_current_workspace_session() -> None:
    session = WorkspaceSession.scratch()

    with workspace_scope(session):
        result = run_shell_command("pwd")

    assert result == "/workspace\n"


def test_shell_adapter_reports_missing_workspace_session() -> None:
    result = run_shell_command("pwd")

    assert "No active workspace session" in result
