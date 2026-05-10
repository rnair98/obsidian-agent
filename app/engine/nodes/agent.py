"""Generic agent-node factory.

Replaces three near-identical ``create_<name>_agent`` modules with one
factory that takes an :class:`AgentSpec` and produces an executor-bound
LangGraph node. The executor is built once per ``make_agent_node`` call
and reused across invocations of the returned coroutine.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from app.core.logger import logger
from app.core.settings import settings
from app.engine.agents.spec import AgentSpec
from app.engine.nodes.builders.agent import (
    build_agent_executor_from_spec,
    run_agent_executor,
)
from app.engine.nodes.types import AgentNode

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime

    from app.engine.nodes.builders.agent import AgentRunResult
    from app.engine.schema import ResearchContext, ResearchState


def make_agent_node(
    spec: AgentSpec,
    *,
    log_streams: bool = False,
    stream_mode: Sequence[str] | None = None,
) -> AgentNode:
    """Create a LangGraph node bound to an :class:`AgentSpec`.

    The executor is built once at factory-call time, not on every node
    invocation — saves three ``ChatOpenAI`` constructions per request.

    Args:
        spec: The agent definition (schema + prompt + tools).
        log_streams: If true, stream the agent and log reasoning/text
            chunks at debug level.
        stream_mode: LangGraph stream modes; defaults to
            ``["messages", "updates"]`` when ``log_streams`` is true.
    """
    executor = build_agent_executor_from_spec(spec)
    effective_modes = (
        list(stream_mode)
        if stream_mode is not None
        else (["messages", "updates"] if log_streams else None)
    )

    async def node(
        state: "ResearchState",
        runtime: "Runtime[ResearchContext]",
        config: "RunnableConfig",
    ) -> "AgentRunResult":
        logger.debug(
            "[{}] use_responses_api={} model={}",
            spec.name.upper(),
            settings.llm.use_responses_api if settings.llm else None,
            settings.llm.model if settings.llm else None,
        )
        return await run_agent_executor(
            executor,
            state=state,
            runtime_context=runtime.context,
            config=config,
            workflow_name=spec.name,
            stream_mode=effective_modes,
            log_stream_chunks=log_streams,
        )

    node.__name__ = f"{spec.name}_node"
    return node
