from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.runtime import Runtime

from app.engine.outputs import SummarizerOutput
from app.engine.tools.io import write_report
from app.logger import logger
from app.settings import settings

if TYPE_CHECKING:
    from langchain.agents import AgentState
    from langchain_core.messages import ResponseT
    from langchain_core.runnables import RunnableConfig
    from langgraph.graph.state import CompiledStateGraph
    from langgraph.runtime import Runtime

    from app.engine.schema import ResearchContext, ResearchState


def create_summarizer_agent() -> "CompiledStateGraph[AgentState[ResponseT]]":
    USE_RESPONSES_API = True
    TOOLS = [write_report]

    def summarizer_node(
        state: ResearchState,
        runtime: Runtime[ResearchContext],
        config: RunnableConfig,
    ) -> dict[str, Any]:
        llm_config = runtime.context.llm_config or settings.llm.to_dict()
        logger.debug(f"[SUMMARIZER] Using responses API: {USE_RESPONSES_API}")
        logger.debug(f"[SUMMARIZER] LLM Config: {llm_config}")

        model = ChatOpenAI(use_responses_api=USE_RESPONSES_API, **llm_config)

        agent_executor = create_agent(
            model=model,
            tools=TOOLS,
            system_prompt=settings.agents.summarizer.system_prompt,
            response_format=SummarizerOutput,
        )
        result = agent_executor.invoke(
            input=state, context=runtime.context, config=config
        )
        return {"messages": result["messages"]}

    return summarizer_node
