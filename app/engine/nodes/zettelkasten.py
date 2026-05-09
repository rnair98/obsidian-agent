from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.logger import logger
from app.core.settings import settings
from app.engine.agents.zettelkasten import SPEC
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


def create_zettelkasten_agent() -> AgentNode:
    async def zettelkasten_node(
        state: ResearchState,
        runtime: Runtime[ResearchContext],
        config: RunnableConfig,
    ) -> AgentRunResult:
        logger.debug(
            "[%s] Using responses API: %s",
            Workflow.ZETTELKASTEN.upper(),
            settings.llm.use_responses_api,
        )
        logger.debug(
            f"[{Workflow.ZETTELKASTEN.upper()}] LLM Config: "
            f"{settings.llm.model_dump(exclude={'api_key'})}"
        )

        agent_executor = build_agent_executor_from_spec(SPEC)

        return await run_agent_executor(
            agent_executor,
            state=state,
            runtime_context=runtime.context,
            config=config,
            workflow_name=Workflow.ZETTELKASTEN,
        )

    return zettelkasten_node
