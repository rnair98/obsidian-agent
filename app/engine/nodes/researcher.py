from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import AnyMessage
from langgraph.runtime import Runtime

from app.core.logger import logger
from app.core.settings import settings
from app.engine.nodes.builders.agent import build_agent_executor, run_agent_executor
from app.engine.nodes.types import Workflow
from app.engine.outputs import ResearcherOutput
from app.engine.tools import MCP_TOOLS, OPENAI_TOOLS
from app.engine.tools.io import save_note
from app.engine.tools.web import fetch_url

if TYPE_CHECKING:
    from langchain.agents import AgentState
    from langchain_core.messages import ResponseT
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.runtime import Runtime

    from app.engine.schema import ResearchContext, ResearchState


def create_researcher_agent() -> "CompiledStateGraph[AgentState[ResponseT]]":
    TOOLS = [
        *OPENAI_TOOLS,
        *MCP_TOOLS,
        fetch_url,
        save_note,
    ]

    def research_node(
        state: ResearchState,
        runtime: Runtime[ResearchContext],
        config: RunnableConfig,
    ) -> dict[str, list[AnyMessage]]:
        llm_config = settings.llm.model_dump()
        logger.debug(
            f"[{Workflow.RESEARCHER.upper()}] Using responses API: "
            f"{llm_config['use_responses_api']}"
        )
        logger.debug(
            f"[{Workflow.RESEARCHER.upper()}] Using model: {llm_config['model']}"
        )

        agent_executor = build_agent_executor(
            tools=TOOLS,
            system_prompt=settings.agents.researcher.system_prompt,
            response_format=ProviderStrategy(ResearcherOutput),
        )

        return run_agent_executor(
            agent_executor,
            state=state,
            runtime_context=runtime.context,
            config=config,
            workflow_name=Workflow.RESEARCHER,
            stream_mode=["messages", "updates"],
            log_stream_chunks=True,
        )

    return research_node
