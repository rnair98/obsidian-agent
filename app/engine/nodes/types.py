from __future__ import annotations

from collections.abc import Awaitable
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

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
    surfacing a 404 from the registry. Distinct from a graph: a workflow
    composes one or more graphs. See ARCHITECTURE.md §5 and §9.
    """

    RESEARCH = "research"
    RESEARCHER = "researcher"
    SUMMARIZER = "summarizer"
    ZETTELKASTEN = "zettelkasten"


class AgentNode(Protocol):
    """Node callable accepted by LangGraph's runtime-injected signature.

    ``config`` is optional because ``_NodeWithRuntime`` only requires
    ``state`` and keyword ``runtime``. The concrete node still annotates
    ``config`` as ``Optional[RunnableConfig]`` so LangGraph injects it.
    """

    def __call__(
        self,
        state: ResearchState,
        *,
        runtime: Runtime[ResearchContext],
        config: RunnableConfig | None = None,
    ) -> Awaitable[AgentRunResult]: ...
