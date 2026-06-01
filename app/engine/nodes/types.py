from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime

    from app.engine.nodes.builders.agent import AgentRunResult
    from app.engine.schema import ResearchContext, ResearchState


class NodeName(StrEnum):
    """Identifier for a single node within a graph."""

    VAULT_PROFILER = "vault_profiler"
    RESEARCHER = "researcher"
    SUMMARIZER = "summarizer"
    ZETTELKASTEN = "zettelkasten"
    PERSIST = "persist"


class WorkflowName(StrEnum):
    """Identifier for an HTTP-invocable workflow.

    Distinct from :class:`NodeName` so the FastAPI route layer can reject
    bare-node identifiers (``persist``) at request validation rather than
    surfacing a 404 from the registry.
    """

    RESEARCH = "research"
    RESEARCHER = "researcher"
    SUMMARIZER = "summarizer"
    ZETTELKASTEN = "zettelkasten"


AgentNode: TypeAlias = Callable[
    ["ResearchState", "Runtime[ResearchContext]", "RunnableConfig"],
    "Awaitable[AgentRunResult]",
]
