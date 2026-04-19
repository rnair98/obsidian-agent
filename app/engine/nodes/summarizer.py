from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.agents.structured_output import ProviderStrategy

from app.core.logger import logger
from app.core.settings import settings
from app.engine.nodes.builders.agent import build_agent_executor, run_agent_executor
from app.engine.nodes.types import AgentNode, Workflow
from app.engine.outputs import SummarizerOutput
from app.engine.tools.io import write_report

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime

    from app.engine.nodes.builders.agent import AgentRunResult
    from app.engine.schema import ResearchContext, ResearchState


def create_summarizer_agent() -> AgentNode:
    TOOLS = [write_report]

    async def summarizer_node(
        state: ResearchState,
        runtime: Runtime[ResearchContext],
        config: RunnableConfig,
    ) -> AgentRunResult:
        logger.debug(
            f"[{Workflow.SUMMARIZER.upper()}] Using responses API: "
            f"{settings.llm.use_responses_api}"
        )
        logger.debug(
            f"[{Workflow.SUMMARIZER.upper()}] LLM Config: "
            f"{settings.llm.model_dump(exclude={'api_key'})}"
        )

        agent_executor = build_agent_executor(
            tools=TOOLS,
            system_prompt=settings.agents.summarizer.system_prompt,
            response_format=ProviderStrategy(SummarizerOutput),
        )

        return await run_agent_executor(
            agent_executor,
            state=state,
            runtime_context=runtime.context,
            config=config,
            workflow_name=Workflow.SUMMARIZER,
        )

    return summarizer_node
