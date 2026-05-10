"""
Centralized workflow execution runner.

This module provides a single entry point for running registered workflows,
handling state initialization, context setup, and graph invocation.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import BaseCheckpointSaver, MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.logger import logger
from app.core.settings import settings
from app.engine.backends import artifacts_backend
from app.engine.nodes.types import WorkflowName
from app.engine.persistence import load_memories
from app.engine.registry import get_workflow
from app.engine.schema import ResearchContext, ResearchRequest, ResearchState


def _initial_context(request: ResearchRequest) -> ResearchContext:
    return ResearchContext(
        search_limit=settings.workflow.search_limit,
        exa_search_type=settings.workflow.exa_search_type,
        fetch_code_context=settings.workflow.fetch_code_context,
        seed_urls=request.seed_urls,
        experiment_snippets=request.experiment_snippets,
    )


def _initial_state(
    workflow_name: WorkflowName,
    request: ResearchRequest,
    memories: list[str],
) -> ResearchState:
    return {
        "messages": [
            SystemMessage(content=f"Starting {workflow_name} workflow."),
            HumanMessage(content=f"Please process the topic: {request.topic}"),
        ],
        "topic": request.topic,
        "search_query": request.search,
        "memories": memories,
        "research_notes": [],
        "experiments": [],
        "code_context": [],
        "sources": [],
        "report": "",
        "zettelkasten_notes": [],
        "reasoning": [],
        "key_insights": [],
    }


@asynccontextmanager
async def _checkpointer() -> AsyncIterator[BaseCheckpointSaver]:
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
    memories = load_memories(settings.MEMORIES_DIR, backend=artifacts_backend())
    state = _initial_state(workflow_name, request, memories)
    context = _initial_context(request)

    async with _checkpointer() as checkpointer:
        graph = get_workflow(workflow_name, checkpointer)
        return await graph.ainvoke(input=state, config=config, context=context)
