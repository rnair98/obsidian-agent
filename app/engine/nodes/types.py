from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Awaitable, Callable, TypeAlias

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime

    from app.engine.nodes.builders.agent import AgentRunResult
    from app.engine.schema import ResearchContext, ResearchState


class Workflow(StrEnum):
    RESEARCHER = "researcher"
    SUMMARIZER = "summarizer"
    ZETTELKASTEN = "zettelkasten"
    PERSIST = "persist"
    RESEARCH = "research"


AgentNode: TypeAlias = Callable[
    ["ResearchState", "Runtime[ResearchContext]", "RunnableConfig"],
    "Awaitable[AgentRunResult]",
]
