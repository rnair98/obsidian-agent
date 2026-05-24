"""
Centralized workflow execution runner.

This module provides a single entry point for running registered workflows,
handling state initialization, context setup, and graph invocation.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.logger import logger
from app.core.settings import settings
from app.engine.backends import assets_backend
from app.engine.nodes.persist import safe_note_id
from app.engine.nodes.types import WorkflowName
from app.engine.registry import get_workflow
from app.engine.schema import (
    ArtifactRef,
    ResearchContext,
    ResearchRequest,
    ResearchState,
    RunArtifacts,
    RunSummary,
    WorkflowRunResponse,
    ZettelArtifactRef,
)
from app.engine.vaults import VaultLayout, resolve_vault
from app.engine.workspace import build_workspace_session
from app.harness.runtime import workspace_scope

_PRIOR_MEMORY_MANIFEST_LIMIT = 25


def _render_prior_memories(vault: VaultLayout) -> str:
    """Build the ``$prior_memories`` system-prompt block from vault state.

    Returns a cold-vault hint when ``.memories/`` is empty so the researcher
    knows not to run discovery shells (`ls /memory`, `grep …`). On a warm
    vault, returns a bounded manifest of filenames so the agent can `cat`
    relevant slugs directly without enumerating the directory itself.
    """
    try:
        entries = vault.backend.list_dir(vault.memories_dir)
    except Exception:  # noqa: BLE001  -- backend may raise on missing dir
        entries = []
    notes = sorted(p.name for p in entries if p.suffix == ".md")
    if not notes:
        return (
            "<prior_memories>\n"
            "`/memory` is empty for this run. Skip the archaeology step "
            "(do not run `ls`, `grep`, or `cat` against `/memory`) and "
            "begin fresh.\n"
            "</prior_memories>"
        )
    head = notes[:_PRIOR_MEMORY_MANIFEST_LIMIT]
    listing = "\n".join(f"- {n}" for n in head)
    overflow = (
        f"\n(+{len(notes) - len(head)} more — `ls /memory` for the full list)"
        if len(notes) > len(head)
        else ""
    )
    return (
        "<prior_memories>\n"
        f"Durable prior research runs are mounted at `/memory` "
        f"({len(notes)} file{'s' if len(notes) != 1 else ''}). Treat these "
        "as privileged context. The manifest below is authoritative — "
        "`cat /memory/<slug>` the ones relevant to the topic instead of "
        "re-enumerating the directory. Extract Key Insights, note what was "
        "already settled, and avoid re-deriving captured conclusions.\n\n"
        f"{listing}{overflow}\n"
        "</prior_memories>"
    )


@asynccontextmanager
async def _checkpointer() -> AsyncIterator[BaseCheckpointSaver[Any]]:
    """Yield a checkpointer — Postgres if configured, else in-memory."""
    if settings.DATABASE_URL:
        async with AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL) as saver:
            await saver.setup()  # idempotent
            yield saver
    else:
        yield MemorySaver()


def _snapshot_memories(vault: VaultLayout) -> set[Path]:
    """Take a pre-run listing of ``.memories/`` for after-the-fact diffing.

    ``persist_artifacts`` writes a timestamped memory file but does not echo
    the written path through the LangGraph state delta. Comparing this
    snapshot against a post-run listing is the cheapest reliable way to
    surface "what did this run write" without expanding ``ResearchState``.
    """
    try:
        return set(vault.backend.list_dir(vault.memories_dir))
    except Exception:  # noqa: BLE001  -- backend may raise on missing dir
        return set()


def _project_run_response(
    *,
    run_id: str,
    workflow_name: WorkflowName,
    request: ResearchRequest,
    state: Mapping[str, Any],
    vault: VaultLayout,
    memories_before: set[Path],
) -> WorkflowRunResponse:
    """Project the final ``ResearchState`` into the public response shape.

    Only emits artifact references for files that actually exist on the
    backend. Standalone agent workflows (researcher/summarizer/zettelkasten)
    don't run the persist node, so most fields are legitimately empty there.
    """
    backend = vault.backend

    def _ref(rel_path: Path) -> ArtifactRef | None:
        if not backend.exists(rel_path):
            return None
        return ArtifactRef(
            path=rel_path.as_posix(),
            absolute_path=str(backend.resolve(rel_path)),
        )

    report_ref = _ref(vault.outputs_dir / "report.md")
    sources_ref = _ref(vault.outputs_dir / "sources.csv")

    zettel_refs: list[ZettelArtifactRef] = []
    seen_ids: set[str] = set()
    for note in state.get("zettelkasten_notes") or []:
        base_id = safe_note_id(note.get("id"))
        safe_id = base_id
        suffix = 2
        # Mirror persist's collision-suffixing so reported paths match disk.
        while safe_id in seen_ids:
            safe_id = f"{base_id}-{suffix}"
            suffix += 1
        seen_ids.add(safe_id)
        rel = vault.notes_dir / f"{safe_id}.md"
        if not backend.exists(rel):
            continue
        zettel_refs.append(
            ZettelArtifactRef(
                id=str(note.get("id") or ""),
                title=str(note.get("title") or ""),
                tags=list(note.get("tags") or []),
                path=rel.as_posix(),
                absolute_path=str(backend.resolve(rel)),
            )
        )

    memories_after = _snapshot_memories(vault)
    new_memories = sorted(
        p for p in memories_after - memories_before if p.suffix == ".md"
    )
    memory_refs = [
        ArtifactRef(
            path=(vault.memories_dir / m.name).as_posix(),
            absolute_path=str(m),
        )
        for m in new_memories
    ]

    sources_state = state.get("sources") or []
    notes_state = state.get("research_notes") or []
    zettels_state = state.get("zettelkasten_notes") or []

    return WorkflowRunResponse(
        run_id=run_id,
        workflow=str(workflow_name),
        topic=str(state.get("topic") or request.topic),
        vault=request.vault,
        artifacts=RunArtifacts(
            report=report_ref,
            sources_csv=sources_ref,
            zettels=zettel_refs,
            memories=memory_refs,
        ),
        summary=RunSummary(
            key_insights=list(state.get("key_insights") or []),
            research_notes_count=len(notes_state),
            sources_count=len(sources_state),
            zettel_count=len(zettels_state),
        ),
    )


async def execute(
    workflow_name: WorkflowName, request: ResearchRequest
) -> WorkflowRunResponse:
    """Execute a registered workflow with the given request."""
    logger.info("Running workflow: {} for topic: {}", workflow_name, request.topic)

    run_id = str(uuid.uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": run_id}}
    state = ResearchState(
        messages=[
            SystemMessage(content=f"Starting {workflow_name} workflow."),
            HumanMessage(content=f"Please process the topic: {request.topic}"),
        ],
        topic=request.topic,
        research_notes=[],
        experiments=[],
        code_context=[],
        sources=[],
        report="",
        zettelkasten_notes=[],
        reasoning=[],
        key_insights=[],
        vault_profile="",  # populated by the vault_profiler node
    )

    vault = await asyncio.to_thread(resolve_vault, request)

    context = ResearchContext(vault=vault)
    # vault_profile is now produced inside the graph by the
    # ``vault_profiler`` node (first node in the research workflow) and
    # consumed by the zettelkasten node directly from state. Only
    # ``prior_memories`` still needs to be baked into a static system
    # prompt at compile time (researcher's ``$prior_memories``).
    prompt_context = {"prior_memories": _render_prior_memories(vault)}

    # Snapshot ``.memories/`` BEFORE the graph runs so we can identify the
    # specific memory file the persist node materializes (its filename
    # encodes a timestamp we don't know up front).
    memories_before = _snapshot_memories(vault)

    async with _checkpointer() as checkpointer:
        graph = get_workflow(workflow_name, checkpointer, prompt_context=prompt_context)

        with workspace_scope(
            build_workspace_session(
                asset_backend=assets_backend(),
                vault=context.vault,
            )
        ):
            result: dict[str, object] = await graph.ainvoke(
                input=state, config=config, context=context
            )

    return _project_run_response(
        run_id=run_id,
        workflow_name=workflow_name,
        request=request,
        state=result,
        vault=vault,
        memories_before=memories_before,
    )
