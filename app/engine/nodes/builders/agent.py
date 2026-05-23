from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Protocol, TypedDict, cast

from langchain.agents.factory import (
    create_agent,  # pyright: ignore[reportUnknownVariableType]
)
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.messages import AnyMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.types import StreamMode
from pydantic import BaseModel

from app.core.logger import logger
from app.core.settings import settings
from app.engine.agents.researcher import ResearcherOutput
from app.engine.agents.spec import AgentSpec
from app.engine.agents.summarizer import SummarizerOutput
from app.engine.agents.zettelkasten import ZettelkastenOutput
from app.engine.nodes.builders.middleware import context_editing, tool_retry
from app.engine.schema import ResearchContext, ResearchState, SourceState, ZettelNote

type StreamChunk = tuple[StreamMode, object]


class AgentExecutor(Protocol):
    """Minimal LangGraph executor surface used by this module."""

    async def ainvoke(
        self,
        input: ResearchState,
        config: RunnableConfig,
        *,
        context: ResearchContext,
    ) -> Mapping[str, object]: ...

    def astream(
        self,
        input: ResearchState,
        config: RunnableConfig,
        *,
        context: ResearchContext,
        stream_mode: Sequence[StreamMode],
    ) -> AsyncIterator[object]: ...


__all__ = [
    "AgentRunResult",
    "build_agent_executor_from_spec",
    "run_agent_executor",
    "structured_response_delta",
]


class AgentRunResult(TypedDict, total=False):
    messages: list[AnyMessage]
    research_notes: list[str]
    key_insights: list[str]
    sources: list[SourceState]
    reasoning: list[str]
    report: str
    zettelkasten_notes: list[ZettelNote]


def _extract_messages(result: Mapping[str, object]) -> list[AnyMessage]:
    messages = result.get("messages", [])
    if not isinstance(messages, list):
        raise TypeError("Agent result did not include a list of messages")
    message_values = cast("list[object]", messages)
    if not all(isinstance(message, BaseMessage) for message in message_values):
        raise TypeError("Agent result messages must be LangChain message objects")
    return cast("list[AnyMessage]", message_values)


def structured_response_delta(response: object) -> AgentRunResult:
    if isinstance(response, ResearcherOutput):
        return {
            "research_notes": response.research_notes,
            "key_insights": response.key_insights,
            "sources": [
                {
                    "title": source.title,
                    "url": source.url,
                    "notes": source.notes,
                    "score": source.score,
                }
                for source in response.sources
            ],
            "reasoning": response.reasoning,
        }
    if isinstance(response, SummarizerOutput):
        return {"report": response.report_content}
    if isinstance(response, ZettelkastenOutput):
        return {
            "zettelkasten_notes": [
                {
                    "id": note.id,
                    "title": note.title,
                    "content": note.content,
                    "tags": note.tags,
                }
                for note in response.notes
            ]
        }
    if isinstance(response, BaseModel):
        logger.debug("Ignoring unsupported structured response: {}", type(response))
    return {}


def _split_stream_chunk(
    chunk: object, modes: Sequence[StreamMode]
) -> StreamChunk | None:
    if len(modes) == 1:
        return modes[0], chunk
    if not isinstance(chunk, tuple) or len(cast("tuple[object, ...]", chunk)) != 2:
        return None
    framed_chunk = cast("tuple[object, object]", chunk)
    if not isinstance(framed_chunk[0], str):
        return None
    return cast("StreamMode", framed_chunk[0]), framed_chunk[1]


def _extract_message_token(data: object) -> object | None:
    if not isinstance(data, tuple) or len(cast("tuple[object, ...]", data)) != 2:
        return None
    return cast("tuple[object, object]", data)[0]


def _extract_updates(data: object) -> list[Mapping[str, object]]:
    if not isinstance(data, Mapping):
        return []
    updates = cast("Mapping[object, object]", data)
    typed_updates: list[Mapping[str, object]] = []
    for update in updates.values():
        if isinstance(update, Mapping):
            typed_updates.append(cast("Mapping[str, object]", update))
    return typed_updates


def build_agent_executor_from_spec(spec: AgentSpec[Any]) -> AgentExecutor:
    """Build an executor straight from an :class:`AgentSpec`.

    Pulls schema, prompt (with placeholder interpolation), tools, and
    per-agent LLM overrides out of the spec — the single source of truth
    for an agent's contract with the model.
    """
    return cast(
        "AgentExecutor",
        create_agent(
            model=ChatOpenAI(**spec.llm_kwargs()),
            tools=spec.tools,
            system_prompt=spec.system_prompt(),
            response_format=ProviderStrategy(spec.output_schema),
            context_schema=ResearchContext,
            middleware=cast("Sequence[Any]", [tool_retry, context_editing]),
        ),
    )


def _extract_text_from_reasoning_block(block: Mapping[str, object]) -> str:
    reasoning = block.get("reasoning")
    if isinstance(reasoning, str):
        return reasoning
    summary = block.get("summary")
    if not isinstance(summary, list):
        return ""
    parts: list[str] = []
    for item in cast("list[object]", summary):
        if not isinstance(item, Mapping):
            continue
        text = cast("Mapping[str, object]", item).get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return " ".join(parts)


def _log_stream_chunk(workflow_name: str, token: object) -> None:
    content_blocks = getattr(token, "content_blocks", None)
    if not isinstance(content_blocks, list):
        return
    label = workflow_name.upper()
    for block in cast("list[object]", content_blocks):
        if not isinstance(block, Mapping):
            continue
        typed_block = cast("Mapping[str, object]", block)
        block_type = typed_block.get("type")
        if block_type == "reasoning":
            text = _extract_text_from_reasoning_block(typed_block)
            if text:
                logger.debug("[{}] reasoning chunk: {}", label, text)
        elif block_type == "text":
            text = typed_block.get("text")
            if isinstance(text, str) and text:
                logger.debug("[{}] text chunk: {}", label, text)


async def run_agent_executor(
    agent_executor: AgentExecutor,
    *,
    state: ResearchState,
    runtime_context: ResearchContext,
    config: RunnableConfig,
    workflow_name: str,
    stream_mode: Sequence[StreamMode] | None = None,
    log_stream_chunks: bool = False,
) -> AgentRunResult:
    """Run agent via invoke or stream and return final messages state."""
    streaming = bool(settings.llm and settings.llm.streaming)

    if not streaming:
        result = await agent_executor.ainvoke(
            input=state, context=runtime_context, config=config
        )
        return {
            "messages": _extract_messages(result),
            **structured_response_delta(result.get("structured_response")),
        }

    final_messages: list[AnyMessage] | None = None
    structured_delta: AgentRunResult = {}
    modes: list[StreamMode] = list(stream_mode or ["messages", "updates"])

    async for chunk in agent_executor.astream(
        input=state,
        context=runtime_context,
        config=config,
        stream_mode=modes,
    ):
        parsed_chunk = _split_stream_chunk(chunk, modes)
        if parsed_chunk is None:
            continue
        mode, data = parsed_chunk

        if mode == "messages" and log_stream_chunks:
            token = _extract_message_token(data)
            if token is not None:
                _log_stream_chunk(workflow_name, token)
        elif mode == "updates":
            for update in _extract_updates(data):
                if not isinstance(update.get("messages"), list):
                    continue
                final_messages = _extract_messages(update)
                if structured_response := update.get("structured_response"):
                    structured_delta = structured_response_delta(structured_response)

    if final_messages is None:
        logger.debug(
            "[{}] Stream returned no final messages; falling back to invoke.",
            workflow_name.upper(),
        )
        result = await agent_executor.ainvoke(
            input=state, context=runtime_context, config=config
        )
        final_messages = _extract_messages(result)
        structured_delta = structured_response_delta(result.get("structured_response"))

    return {"messages": final_messages, **structured_delta}
