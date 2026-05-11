from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.engine.agents.researcher import SPEC as RESEARCHER_SPEC
from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.executor import execute
from app.engine.nodes.types import WorkflowName
from app.engine.schema import ResearchRequest
from app.engine.tools.shell import run_shell_command
from app.engine.workspace import build_workspace_session
from app.harness.session import WorkspaceSession


def test_researcher_spec_exposes_shell_tool() -> None:
    tool_names = {getattr(tool, "name", "") for tool in RESEARCHER_SPEC.tools}

    assert "shell" in tool_names


@pytest.mark.asyncio
async def test_executor_installs_workspace_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeGraph:
        async def ainvoke(
            self,
            *,
            input: object,
            config: object,
            context: object,
        ) -> dict[str, str]:
            return {"pwd": run_shell_command("pwd")}

    def fake_get_workflow(name: WorkflowName, checkpointer: object) -> FakeGraph:
        return FakeGraph()

    monkeypatch.setattr("app.engine.executor.get_workflow", fake_get_workflow)
    monkeypatch.setattr(
        "app.engine.executor.build_workspace_session",
        WorkspaceSession.scratch,
    )

    result: dict[str, Any] = await execute(
        WorkflowName.RESEARCH,
        ResearchRequest(topic="typed workspace harness"),
    )

    assert result["pwd"] == "/workspace\n"


def test_workspace_memory_mount_uses_artifact_memories(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = InProcessFilesystemBackend(base_path=tmp_path)
    backend.write_text("memories/prior.md", "settled fact\n")

    monkeypatch.setattr("app.engine.workspace.artifacts_backend", lambda: backend)
    monkeypatch.setattr("app.core.settings.settings.MEMORIES_DIR", Path("memories"))
    monkeypatch.setattr("app.core.settings.settings.VAULT_DIR", Path("vault"))

    session = build_workspace_session()

    assert session.run("ls /memory").stdout == "prior.md\n"
    assert session.run("grep settled /memory/prior.md").stdout == "settled fact\n"
    assert session.run("write /memory/scratch.md new-fact").exit_code == 0
    assert backend.read_text("memories/scratch.md") == "new-fact"
