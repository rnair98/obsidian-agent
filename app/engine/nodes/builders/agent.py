from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypedDict

from langchain.agents import create_agent
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import AnyMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from app.core.logger import logger
from app.core.settings import settings
from app.engine.agents.spec import AgentSpec
from app.engine.nodes.builders.middleware import context_editing, tool_retry
from app.engine.schema import ResearchContext, ResearchState

__all__ = [
    "AgentRunResult",
    "build_agent_executor_from_spec",
    "run_agent_executor",
]


class AgentRunResult(TypedDict):
    messages: list[AnyMessage]


def _extract_messages(result: Mapping[str, object]) -> list[AnyMessage]:
    messages = result.get("messages")
    if not isinstance(messages, list):
        raise TypeError("Agent result did not include a list of messages")
    if not all(isinstance(m, BaseMessage) for m in messages):
        raise TypeError("Agent result messages must be LangChain message objects")
    return messages


def build_agent_executor_from_spec(spec: AgentSpec) -> CompiledStateGraph:
    """Build an executor straight from an :class:`AgentSpec`.

    Pulls schema, prompt (with placeholder interpolation), tools, and
    per-agent LLM overrides out of the spec — the single source of truth
    for an agent's contract with the model.
    """
    return create_agent(
        model=ChatOpenAI(**spec.llm_kwargs()),
        tools=list(spec.tools),
        system_prompt=spec.system_prompt(),
        response_format=ProviderStrategy(spec.output_schema),
        middleware=[tool_retry, context_editing],
    )


def _extract_text_from_reasoning_block(block: Mapping[str, object]) -> str:
    reasoning = block.get("reasoning")
    if isinstance(reasoning, str):
        return reasoning
    summary = block.get("summary")
    if not isinstance(summary, list):
        return ""
    parts = [
        item["text"]
        for item in summary
        if isinstance(item, Mapping)
        and isinstance(item.get("text"), str)
        and item["text"]
    ]
    return " ".join(parts)


def _log_stream_chunk(workflow_name: str, token: object) -> None:
    content_blocks = getattr(token, "content_blocks", None)
    if not isinstance(content_blocks, list):
        return
    label = workflow_name.upper()
    for block in content_blocks:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "reasoning":
            text = _extract_text_from_reasoning_block(block)
            if text:
                logger.debug("[{}] reasoning chunk: {}", label, text)
        elif block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                logger.debug("[{}] text chunk: {}", label, text)


async def run_agent_executor(
    agent_executor: CompiledStateGraph,
    *,
    state: ResearchState,
    runtime_context: ResearchContext,
    config: RunnableConfig,
    workflow_name: str,
    stream_mode: Sequence[str] | None = None,
    log_stream_chunks: bool = False,
) -> AgentRunResult:
    """Run agent via invoke or stream and return final messages state."""
    streaming = bool(settings.llm and settings.llm.streaming)

    if not streaming:
        result = await agent_executor.ainvoke(
            input=state, context=runtime_context, config=config
        )
        return {"messages": _extract_messages(result)}

    final_messages: list[AnyMessage] | None = None
    modes = list(stream_mode or ["messages", "updates"])

    async for chunk in agent_executor.astream(
        input=state,
        context=runtime_context,
        config=config,
        stream_mode=modes,
    ):
        # LangGraph yields ``(mode, data)`` tuples only when multiple
        # stream modes are requested. With a single mode the chunk is the
        # bare payload — and that payload is itself often a 2-tuple
        # (``messages`` mode emits ``(AIMessageChunk, metadata)``), so we
        # cannot use ``isinstance(chunk, tuple)`` alone to detect framing.
        if len(modes) == 1:
            mode, data = modes[0], chunk
        elif isinstance(chunk, tuple) and len(chunk) == 2 and isinstance(chunk[0], str):
            mode, data = chunk
        else:
            continue

        if mode == "messages" and log_stream_chunks:
            if isinstance(data, tuple) and len(data) == 2:
                token, _ = data
                _log_stream_chunk(workflow_name, token)
        elif mode == "updates" and isinstance(data, dict):
            for update in data.values():
                if isinstance(update, Mapping) and isinstance(
                    update.get("messages"), list
                ):
                    final_messages = _extract_messages(update)

    if final_messages is None:
        logger.debug(
            "[{}] Stream returned no final messages; falling back to invoke.",
            workflow_name.upper(),
        )
        result = await agent_executor.ainvoke(
            input=state, context=runtime_context, config=config
        )
        final_messages = _extract_messages(result)

    return {"messages": final_messages}
