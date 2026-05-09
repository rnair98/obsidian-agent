from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.logger import logger
from app.core.settings import settings
from app.engine.agents.researcher import SPEC
from app.engine.nodes.builders.agent import (
    build_agent_executor_from_spec,
    run_agent_executor,
)
from app.engine.nodes.types import AgentNode, Workflow

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime

    from app.engine.nodes.builders.agent import AgentRunResult
    from app.engine.schema import ResearchContext, ResearchState


def create_researcher_agent() -> AgentNode:
    async def research_node(
        state: ResearchState,
        runtime: Runtime[ResearchContext],
        config: RunnableConfig,
    ) -> AgentRunResult:
        llm_config = settings.llm.model_dump()
        logger.debug(
            f"[{Workflow.RESEARCHER.upper()}] Using responses API: "
            f"{llm_config['use_responses_api']}"
        )
        logger.debug(
            f"[{Workflow.RESEARCHER.upper()}] Using model: {llm_config['model']}"
        )

        agent_executor = build_agent_executor_from_spec(SPEC)

        return await run_agent_executor(
            agent_executor,
            state=state,
            runtime_context=runtime.context,
            config=config,
            workflow_name=Workflow.RESEARCHER,
            stream_mode=["messages", "updates"],
            log_stream_chunks=True,
        )

    return research_node
