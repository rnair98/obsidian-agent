"""
Centralized workflow execution runner.

This module provides a single entry point for running registered workflows,
handling state initialization, context setup, and graph invocation.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.logger import logger
from app.core.settings import settings
from app.engine.backends import assets_backend
from app.engine.nodes.types import WorkflowName
from app.engine.registry import get_workflow
from app.engine.schema import ResearchContext, ResearchRequest, ResearchState
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


async def execute(
    workflow_name: WorkflowName, request: ResearchRequest
) -> dict[str, object]:
    """Execute a registered workflow with the given request."""
    logger.info("Running workflow: {} for topic: {}", workflow_name, request.topic)

    config: RunnableConfig = {"configurable": {"thread_id": str(uuid.uuid4())}}
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
            return result
