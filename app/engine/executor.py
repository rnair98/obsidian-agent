"""
Centralized workflow execution runner.

This module provides a single entry point for running registered workflows,
handling state initialization, context setup, and graph invocation.
"""

from langchain_core.messages import HumanMessage, SystemMessage

from app.engine.registry import get_workflow
from app.engine.schema import ResearchContext, ResearchRequest, ResearchState
from app.engine.tools.io import load_memories
from app.logger import logger
from app.settings import settings


def execute(workflow_name: str, request: ResearchRequest) -> dict:
    """
    Execute a registered workflow with the given request.
    """
    logger.info(f"Running workflow: {workflow_name} for topic: {request.topic}")

    graph = get_workflow(workflow_name)

    memories = load_memories(settings.MEMORIES_DIR)

    context = ResearchContext(
        search_limit=request.search_limit,
        exa_search_type=request.exa_search_type,
        fetch_code_context=request.fetch_code_context,
        seed_urls=request.seed_urls,
        experiment_snippets=request.experiment_snippets,
        llm_config=request.llm_config,
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

    result = graph.invoke(input=state, context=context)

    return result
