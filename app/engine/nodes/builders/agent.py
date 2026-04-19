from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TypeAlias, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AnyMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph

from app.core.logger import logger
from app.core.settings import settings
from app.engine.schema import ResearchContext, ResearchState


class AgentRunResult(TypedDict):
    messages: list[AnyMessage]


class StreamPart(TypedDict):
    type: str
    data: object


StreamChunk: TypeAlias = tuple[str, object] | StreamPart


def _extract_messages(result: Mapping[str, object]) -> list[AnyMessage]:
    messages = result.get("messages")
    if not isinstance(messages, list):
        raise TypeError("Agent result did not include a list of messages")

    if not all(isinstance(message, BaseMessage) for message in messages):
        raise TypeError("Agent result messages must be LangChain message objects")

    return messages


def build_agent_executor(
    *,
    tools: Sequence[object],
    system_prompt: str,
    response_format: object,
) -> CompiledStateGraph:
    """Build a LangChain agent executor with shared OpenAI model config."""

    return create_agent(
        model=ChatOpenAI(**settings.llm.model_dump(mode="python")),
        tools=tools,
        system_prompt=system_prompt,
        response_format=response_format,
    )


def _extract_text_from_reasoning_block(block: Mapping[str, object]) -> str:
    reasoning = block.get("reasoning")
    if isinstance(reasoning, str):
        return reasoning

    summary = block.get("summary")
    if isinstance(summary, list):
        parts: list[str] = []
        for item in summary:
            if isinstance(item, Mapping):
                text = item.get("text")
                if isinstance(text, str) and text:
                    parts.append(text)
        return " ".join(parts)
    return ""


def _log_stream_chunk(workflow_name: str, token: object) -> None:
    content_blocks = getattr(token, "content_blocks", None)
    if not isinstance(content_blocks, list):
        return

    for block in content_blocks:
        if not isinstance(block, Mapping):
            continue

        block_type = block.get("type")
        if block_type == "reasoning":
            reasoning_text = _extract_text_from_reasoning_block(block)
            if reasoning_text:
                logger.debug(
                    f"[{workflow_name.upper()}] reasoning chunk: {reasoning_text}"
                )
        elif block_type == "text":
            text = block.get("text")
            if isinstance(text, str) and text:
                logger.debug(f"[{workflow_name.upper()}] text chunk: {text}")


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
    streaming = bool(settings.llm.streaming)

    if not streaming:
        result = await agent_executor.ainvoke(
            input=state,
            context=runtime_context,
            config=config,
        )
        return {"messages": _extract_messages(result)}

    final_messages: list[AnyMessage] | None = None
    stream = agent_executor.astream(
        input=state,
        context=runtime_context,
        config=config,
        stream_mode=list(stream_mode or ["messages", "updates"]),
        version="v2",
    )

    async for chunk in stream:
        if isinstance(chunk, tuple) and len(chunk) == 2:
            mode, data = chunk
            if (
                mode == "messages"
                and log_stream_chunks
                and isinstance(data, tuple)
                and len(data) == 2
            ):
                token, _ = data
                _log_stream_chunk(workflow_name, token)
            elif mode == "updates" and isinstance(data, dict):
                for _, update in data.items():
                    if isinstance(update, Mapping):
                        messages = update.get("messages")
                        if isinstance(messages, list):
                            final_messages = _extract_messages({"messages": messages})
            continue

        if not isinstance(chunk, dict):
            continue

        chunk_type = chunk.get("type")
        data = chunk.get("data")

        if (
            chunk_type == "messages"
            and log_stream_chunks
            and isinstance(data, tuple)
            and len(data) == 2
        ):
            token, _ = data
            _log_stream_chunk(workflow_name, token)
        elif chunk_type == "updates" and isinstance(data, dict):
            for _, update in data.items():
                if isinstance(update, Mapping):
                    messages = update.get("messages")
                    if isinstance(messages, list):
                        final_messages = _extract_messages({"messages": messages})

    if final_messages is None:
        logger.debug(
            f"[{workflow_name.upper()}] Stream returned no final messages; "
            "falling back to invoke."
        )
        result = await agent_executor.ainvoke(
            input=state,
            context=runtime_context,
            config=config,
        )
        final_messages = _extract_messages(result)

    return {"messages": final_messages}
