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
from app.engine.vaults import resolve_vault
from app.engine.workspace import build_workspace_session
from app.harness.runtime import workspace_scope


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
    )

    vault = await asyncio.to_thread(resolve_vault, request)

    context = ResearchContext(vault=vault)

    async with _checkpointer() as checkpointer:
        graph = get_workflow(workflow_name, checkpointer)

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
