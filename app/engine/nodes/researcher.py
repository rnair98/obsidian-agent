from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.runtime import Runtime

from app.engine.outputs import ResearcherOutput
from app.engine.tools import MCP_TOOLS, OPENAI_TOOLS
from app.engine.tools.io import save_note
from app.engine.tools.web import fetch_url
from app.logger import logger
from app.settings import settings

if TYPE_CHECKING:
    from langchain.agents import AgentState
    from langchain_core.messages import ResponseT
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.runtime import Runtime

    from app.engine.schema import ResearchContext, ResearchState


def create_researcher_agent() -> "CompiledStateGraph[AgentState[ResponseT]]":
    USE_RESPONSES_API = True

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
    ) -> dict[str, Any]:
        llm_config = runtime.context.llm_config or settings.llm.to_dict()
        logger.debug(f"[RESEARCHER] Using responses API: {USE_RESPONSES_API}")
        logger.debug(f"[RESEARCHER] LLM Config: {llm_config}")

        model = ChatOpenAI(use_responses_api=USE_RESPONSES_API, **llm_config)

        agent_executor = create_agent(
            model=model,
            tools=TOOLS,
            system_prompt=settings.agents.researcher.system_prompt,
            response_format=ResearcherOutput,
        )
        result = agent_executor.invoke(
            input=state, context=runtime.context, config=config
        )
        return {"messages": result["messages"]}

    return research_node
