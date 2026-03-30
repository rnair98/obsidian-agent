"""
Centralized workflow execution runner.

This module provides a single entry point for running registered workflows,
handling state initialization, context setup, and graph invocation.
"""

import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.logger import logger
from app.core.settings import settings
from app.engine.registry import get_workflow
from app.engine.schema import ResearchContext, ResearchRequest, ResearchState
from app.engine.tools.io import load_memories


def execute(workflow_name: str, request: ResearchRequest) -> dict:
    """
    Execute a registered workflow with the given request.
    """
    logger.info(f"Running workflow: {workflow_name} for topic: {request.topic}")

    checkpointer = AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL)
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid.uuid4())}}

    graph = get_workflow(workflow_name, checkpointer)

    memories = load_memories(settings.MEMORIES_DIR)

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

    result = graph.invoke(
        input=state,
        config=config,
        context=context,
    )

    return result
