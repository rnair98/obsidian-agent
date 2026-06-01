from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any, Protocol, TypedDict, cast

from langchain.agents.factory import (
    create_agent,  # pyright: ignore[reportUnknownVariableType]
)
from langchain.agents.structured_output import ProviderStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AnyMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langchain_groq import ChatGroq
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
    messages = result.get("messages")
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


# Provider-agnostic keys we accept in per-agent ``llm:`` dicts. Anything
# not in this set is provider-specific and passed through verbatim.
_GROQ_DROPPED_OPENAI_KEYS = frozenset(
    {
        # OpenAI Responses-API specific
        "use_responses_api",
        "reasoning",
        "verbosity",
        "stream_usage",
        "context_management",
        # Cross-provider but OpenAI-namespaced in our global ``llm:`` block:
        # ``LLM__API_KEY`` / ``LLM__BASE_URL`` are the OpenAI key/host and
        # MUST NOT leak to ChatGroq. Groq auth comes from
        # ``settings.GROQ_API_KEY`` (see below).
        "api_key",
        "base_url",
        # Already translated below
        "model",
        "timeout",
    }
)


def _build_chat_model(kwargs: dict[str, Any]) -> BaseChatModel:
    """Construct a chat model from merged LLM kwargs, switching on ``provider``."""
    kwargs = dict(kwargs)  # defensive copy; do not mutate caller's dict
    provider = str(kwargs.pop("provider", "openai")).lower()
    if provider == "openai":
        return ChatOpenAI(**kwargs)
    if provider == "groq":
        groq_kwargs: dict[str, Any] = {
            k: v
            for k, v in kwargs.items()
            if k not in _GROQ_DROPPED_OPENAI_KEYS and v is not None
        }
        if "model" in kwargs:
            groq_kwargs["model_name"] = kwargs["model"]
        if "timeout" in kwargs and kwargs["timeout"] is not None:
            groq_kwargs["request_timeout"] = kwargs["timeout"]
        # Auth: take ONLY ``settings.GROQ_API_KEY`` (or an explicit
        # ``groq_api_key`` override in YAML/spec). We deliberately do
        # NOT inherit ``api_key`` / ``base_url`` from merged kwargs:
        # those carry the OpenAI key/host from the global ``llm:``
        # block (``LLM__API_KEY`` in .env). Forwarding them to ChatGroq
        # produces a 401.
        api_key = kwargs.get("groq_api_key") or settings.GROQ_API_KEY
        if api_key:
            groq_kwargs["groq_api_key"] = api_key
        groq_base = kwargs.get("groq_api_base")
        if groq_base:
            groq_kwargs["groq_api_base"] = groq_base
        return ChatGroq(**groq_kwargs)
    raise ValueError(
        f"unknown LLM provider: {provider!r} (expected 'openai' or 'groq')"
    )


def build_agent_executor_from_spec(
    spec: AgentSpec[Any],
    *,
    prompt_context: Mapping[str, str] | None = None,
) -> AgentExecutor:
    """Build an executor straight from an :class:`AgentSpec`."""
    return cast(
        "AgentExecutor",
        create_agent(
            model=_build_chat_model(spec.llm_kwargs()),
            tools=spec.tools,
            system_prompt=spec.system_prompt(prompt_context),
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


def _flush_reasoning(buffer: list[str], label: str) -> None:
    """Emit the buffered reasoning trace for a single agent turn as one block."""
    block = "".join(buffer).strip()
    buffer.clear()
    if not block:
        return
    logger.opt(colors=True).debug("[{}] <i>{}</i>", label, block)


def _log_stream_chunk(workflow_name: str, token: object, buffer: list[str]) -> None:
    """Accumulate reasoning chunks; ignore raw text tokens."""
    content_blocks = getattr(token, "content_blocks", None)
    if not isinstance(content_blocks, list):
        return
    for block in cast("list[object]", content_blocks):
        if not isinstance(block, Mapping):
            continue
        typed_block = cast("Mapping[str, object]", block)
        if typed_block.get("type") != "reasoning":
            continue
        text = _extract_text_from_reasoning_block(typed_block)
        if text:
            buffer.append(text)


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
    reasoning_buffer: list[str] = []

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
                _log_stream_chunk(workflow_name, token, reasoning_buffer)
        elif mode == "updates":
            for update in _extract_updates(data):
                if not isinstance(update.get("messages"), list):
                    continue
                if log_stream_chunks:
                    _flush_reasoning(reasoning_buffer, workflow_name.upper())
                final_messages = _extract_messages(update)
                if structured_response := update.get("structured_response"):
                    structured_delta = structured_response_delta(structured_response)

    if log_stream_chunks:
        _flush_reasoning(reasoning_buffer, workflow_name.upper())

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
