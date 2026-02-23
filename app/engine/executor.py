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
from app.engine.tools.github import get_github_repo
from app.engine.tools.io import load_memories
from app.services.github.auth import get_github_client


def execute(workflow_name: str, request: ResearchRequest) -> dict:
    """
    Execute a registered workflow with the given request.
    """
    logger.info(f"Running workflow: {workflow_name} for topic: {request.topic}")

    checkpointer = AsyncPostgresSaver.from_conn_string(settings.DATABASE_URL)
    config: RunnableConfig = {"configurable": {"thread_id": str(uuid.uuid4())}}

    graph = get_workflow(workflow_name, checkpointer)

    memories = load_memories(settings.MEMORIES_DIR)

    github_client = get_github_client()
    github_repo = (
        get_github_repo(request.github_repo_name)
        if request.github_repo_name
        else None
    )
    context = ResearchContext(
        search_limit=request.search_limit,
        exa_search_type=request.exa_search_type,
        fetch_code_context=request.fetch_code_context,
        seed_urls=request.seed_urls,
        experiment_snippets=request.experiment_snippets,
        llm_config=request.llm_config,
        github_client=github_client,
        github_repo=github_repo,
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
