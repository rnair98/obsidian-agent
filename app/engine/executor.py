"""
Centralized workflow execution runner.

This module provides a single entry point for running registered workflows,
handling state initialization, context setup, and graph invocation.
"""

import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.logger import logger
from app.core.settings import settings
from app.engine.backends import get_filesystem_backend
from app.engine.nodes.types import Workflow
from app.engine.registry import get_workflow
from app.engine.schema import ResearchContext, ResearchRequest, ResearchState
from app.engine.tools.io import load_memories


async def execute(
    workflow_name: Workflow, request: ResearchRequest
) -> dict[str, object]:
    """
    Execute a registered workflow with the given request.
    """
    logger.info(f"Running workflow: {workflow_name} for topic: {request.topic}")

    config: RunnableConfig = {"configurable": {"thread_id": str(uuid.uuid4())}}

    backend = get_filesystem_backend(
        backend_type=settings.filesystem.backend_type,
        base_path=settings.filesystem.base_path,
    )
    memories = load_memories(settings.MEMORIES_DIR, backend=backend)

    context = ResearchContext(
        search_limit=settings.workflow.search_limit,
        exa_search_type=settings.workflow.exa_search_type,
        fetch_code_context=settings.workflow.fetch_code_context,
        seed_urls=request.seed_urls,
        experiment_snippets=request.experiment_snippets,
    )

    state = ResearchState(
        messages=[
            SystemMessage(content=f"Starting {workflow_name} workflow."),
            HumanMessage(content=f"Please process the topic: {request.topic}"),
        ],
        topic=request.topic,
        search_query=request.search,
        memories=memories,
        research_notes=[],
        experiments=[],
        code_context=[],
        sources=[],
        report="",
        zettelkasten_notes=[],
        reasoning=[],
        key_insights=[],
    )

    if settings.DATABASE_URL:
        async with AsyncPostgresSaver.from_conn_string(
            settings.DATABASE_URL
        ) as checkpointer:
            # Idempotent; creates checkpoint tables on first run.
            await checkpointer.setup()
            return await _run(workflow_name, state, context, config, checkpointer)

    return await _run(workflow_name, state, context, config, MemorySaver())


async def _run(
    workflow_name: Workflow,
    state: ResearchState,
    context: ResearchContext,
    config: RunnableConfig,
    checkpointer,
) -> dict[str, object]:
    graph = get_workflow(workflow_name, checkpointer)
    return await graph.ainvoke(input=state, config=config, context=context)
