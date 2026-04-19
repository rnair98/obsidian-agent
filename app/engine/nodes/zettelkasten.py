from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import AnyMessage
from langgraph.runtime import Runtime

from app.core.logger import logger
from app.core.settings import settings
from app.engine.nodes.builders.agent import build_agent_executor, run_agent_executor
from app.engine.nodes.types import Workflow
from app.engine.outputs import ZettelkastenOutput
from app.engine.tools.io import write_zettelkasten_notes

if TYPE_CHECKING:
    from langchain.agents import AgentState
    from langchain_core.messages import ResponseT
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.runtime import Runtime

    from app.engine.schema import ResearchContext, ResearchState


def create_zettelkasten_agent() -> "CompiledStateGraph[AgentState[ResponseT]]":
    TOOLS = [write_zettelkasten_notes]

    def zettelkasten_node(
        state: ResearchState,
        runtime: Runtime[ResearchContext],
        config: RunnableConfig,
    ) -> dict[str, list[AnyMessage]]:
        logger.debug(
            "[%s] Using responses API: %s",
            Workflow.ZETTELKASTEN.upper(),
            settings.llm.use_responses_api,
        )
        logger.debug(
            f"[{Workflow.ZETTELKASTEN.upper()}] LLM Config: "
            f"{settings.llm.model_dump(exclude={'api_key'})}"
        )

        agent_executor = build_agent_executor(
            tools=TOOLS,
            system_prompt=settings.agents.zettelkasten.system_prompt,
            response_format=ProviderStrategy(ZettelkastenOutput),
        )

        return run_agent_executor(
            agent_executor,
            state=state,
            runtime_context=runtime.context,
            config=config,
            workflow_name=Workflow.ZETTELKASTEN,
        )

    return zettelkasten_node
