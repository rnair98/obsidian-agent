"""Tests for ``executor._project_run_response``.

Exercises the typed projection from final ``ResearchState`` + ``VaultLayout``
into ``WorkflowRunResponse``. The persist node is invoked first to lay down
real artifacts so the projector's existence checks have something to find.
"""

from __future__ import annotations

from pathlib import Path

from langgraph.runtime import Runtime

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.executor import _project_run_response, _snapshot_memories
from app.engine.nodes.persist import persist_artifacts
from app.engine.nodes.types import WorkflowName
from app.engine.schema import (
    LocalVaultRequest,
    ResearchContext,
    ResearchRequest,
    ResearchState,
)
from app.engine.vaults import VaultLayout


def _layout(backend: InProcessFilesystemBackend) -> VaultLayout:
    return VaultLayout(
        backend=backend,
        root=Path("."),
        notes_dir=Path("notes"),
        outputs_dir=Path("outputs"),
        memories_dir=Path(".memories"),
    )


def _state() -> ResearchState:
    return ResearchState(
        messages=[],
        topic="typed response shape",
        research_notes=["note-a", "note-b"],
        experiments=[],
        code_context=[],
        sources=[{"title": "T", "url": "https://x", "notes": "", "provider": "exa"}],
        report="# Report\n\nsynthesis",
        zettelkasten_notes=[
            {
                "id": "typed-workspace",
                "title": "Typed workspace",
                "content": "shell writes ordinary files",
                "tags": ["workspace", "agent"],
            }
        ],
        reasoning=["picked exa"],
        key_insights=["langgraph state is a TypedDict"],
        vault_profile="",
    )


def _request(vault_path: Path) -> ResearchRequest:
    return ResearchRequest(
        topic="typed response shape",
        vault=LocalVaultRequest(type="local", path=vault_path),
    )


def test_project_run_response_emits_refs_for_persisted_research_run(
    tmp_path: Path,
) -> None:
    backend = InProcessFilesystemBackend(base_path=tmp_path)
    vault = _layout(backend)
    backend.mkdir(vault.memories_dir)  # ensure pre-run snapshot is empty
    memories_before = _snapshot_memories(vault)

    # Materialize the full artifact set the way the research graph would.
    persist_artifacts(_state(), Runtime(context=ResearchContext(vault=vault)))

    response = _project_run_response(
        run_id="run-123",
        workflow_name=WorkflowName.RESEARCH,
        request=_request(tmp_path),
        state=_state(),
        vault=vault,
        memories_before=memories_before,
    )

    assert response.run_id == "run-123"
    assert response.workflow == WorkflowName.RESEARCH.value
    assert response.topic == "typed response shape"
    # Report + sources.csv refs land where persist wrote them.
    assert response.artifacts.report is not None
    assert response.artifacts.report.path == "outputs/report.md"
    assert response.artifacts.report.absolute_path == str(
        (tmp_path / "outputs/report.md").resolve()
    )
    assert response.artifacts.sources_csv is not None
    assert response.artifacts.sources_csv.path == "outputs/sources.csv"
    # Zettel refs carry agent-supplied metadata + the on-disk path.
    assert len(response.artifacts.zettels) == 1
    z = response.artifacts.zettels[0]
    assert z.id == "typed-workspace"
    assert z.title == "Typed workspace"
    assert z.tags == ["workspace", "agent"]
    assert z.path == "notes/typed-workspace.md"
    # Exactly one new memory file was written during this run.
    assert len(response.artifacts.memories) == 1
    assert response.artifacts.memories[0].path.startswith(".memories/")
    # Summary mirrors state cardinalities.
    assert response.summary.research_notes_count == 2
    assert response.summary.sources_count == 1
    assert response.summary.zettel_count == 1
    assert response.summary.key_insights == ["langgraph state is a TypedDict"]


def test_project_run_response_omits_refs_when_nothing_persisted(
    tmp_path: Path,
) -> None:
    """Standalone agent workflows never reach the persist node — so the
    projector must emit empty artifact slots rather than dangling refs."""
    backend = InProcessFilesystemBackend(base_path=tmp_path)
    vault = _layout(backend)
    memories_before = _snapshot_memories(vault)

    response = _project_run_response(
        run_id="run-empty",
        workflow_name=WorkflowName.RESEARCHER,
        request=_request(tmp_path),
        state=_state(),
        vault=vault,
        memories_before=memories_before,
    )

    assert response.artifacts.report is None
    assert response.artifacts.sources_csv is None
    assert response.artifacts.zettels == []
    assert response.artifacts.memories == []
    # Summary still reflects whatever the agents produced in-state.
    assert response.summary.research_notes_count == 2
    assert response.summary.zettel_count == 1
