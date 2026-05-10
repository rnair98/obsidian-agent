from __future__ import annotations

from typing import Any

import pytest

from app.engine.agents.researcher import SPEC as RESEARCHER_SPEC
from app.engine.executor import execute
from app.engine.nodes.types import WorkflowName
from app.engine.schema import ResearchRequest
from app.engine.tools.shell import run_shell_command


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

    def fake_load_memories(*args: object, **kwargs: object) -> list[str]:
        return []

    monkeypatch.setattr("app.engine.executor.get_workflow", fake_get_workflow)
    monkeypatch.setattr("app.engine.executor.load_memories", fake_load_memories)
    monkeypatch.setattr("app.engine.executor.artifacts_backend", lambda: object())

    result: dict[str, Any] = await execute(
        WorkflowName.RESEARCH,
        ResearchRequest(topic="typed workspace harness"),
    )

    assert result["pwd"] == "/workspace\n"
