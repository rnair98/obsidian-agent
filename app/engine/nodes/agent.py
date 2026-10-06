"""Generic agent-node factory.

Replaces three near-identical ``create_<name>_agent`` modules with one
factory that takes an :class:`AgentSpec` and produces an executor-bound
LangGraph node. The executor is built once per ``make_agent_node`` call
and reused across invocations of the returned coroutine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Optional

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import StreamMode

from app.core.logger import logger
from app.core.settings import settings
from app.engine.agents.spec import AgentSpec
from app.engine.nodes.builders.agent import (
    AgentExecutor,
    AgentRunResult,
    build_agent_executor_from_spec,
    run_agent_executor,
)
from app.engine.nodes.types import AgentNode
from app.engine.schema import ResearchContext, ResearchState


def make_agent_node(
    spec: AgentSpec[Any],
    *,
    log_streams: bool = False,
    stream_mode: Sequence[StreamMode] | None = None,
    prompt_context: Mapping[str, str] | None = None,
) -> AgentNode:
    """Create a LangGraph node bound to an :class:`AgentSpec`.

    The executor is built once at factory-call time, not on every node
    invocation — saves three ``ChatOpenAI`` constructions per request.
    """
    executor: AgentExecutor = build_agent_executor_from_spec(
        spec, prompt_context=prompt_context
    )
    effective_modes: list[StreamMode] | None = (
        list(stream_mode)
        if stream_mode is not None
        else (["messages", "updates"] if log_streams else None)
    )

    async def node(
        state: ResearchState,
        *,
        runtime: Runtime[ResearchContext],
        # `X | None` stringifies to a form LangGraph's injector does not
        # recognize under `from __future__ import annotations`.
        config: Optional[RunnableConfig] = None,
    ) -> AgentRunResult:
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
            config=config if config is not None else {},
            workflow_name=spec.name,
            stream_mode=effective_modes,
            log_stream_chunks=log_streams,
        )

    node.__name__ = f"{spec.name}_node"
    return node
