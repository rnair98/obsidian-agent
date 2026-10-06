from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from langchain_core.messages import SystemMessage
from langgraph.constants import END, START
from langgraph.graph.state import StateGraph

from app.engine.agents.researcher import SPEC as RESEARCHER_SPEC
from app.engine.agents.summarizer import SPEC as SUMMARIZER_SPEC
from app.engine.agents.zettelkasten import SPEC as ZETTELKASTEN_SPEC
from app.engine.nodes.agent import make_agent_node
from app.engine.nodes.builders.agent import (
    build_agent_executor_from_spec,
    run_agent_executor,
)
from app.engine.nodes.persist import persist_artifacts
from app.engine.nodes.types import NodeName
from app.engine.nodes.vault_profiler import vault_profiler_node
from app.engine.schema import ResearchContext, ResearchState

if TYPE_CHECKING:
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime

    from app.engine.nodes.builders.agent import AgentRunResult


def build_research_graph(
    *,
    prompt_context: Mapping[str, str] | None = None,
) -> StateGraph:
    graph = StateGraph[
        ResearchState,
        ResearchContext,
        ResearchState,
        ResearchState,
    ](ResearchState)

    graph.add_node(NodeName.VAULT_PROFILER, vault_profiler_node)
    graph.add_node(
        NodeName.RESEARCHER,
        make_agent_node(
            RESEARCHER_SPEC, log_streams=True, prompt_context=prompt_context
        ),
    )
    graph.add_node(NodeName.SUMMARIZER, make_agent_node(SUMMARIZER_SPEC))
    graph.add_node(NodeName.ZETTELKASTEN, _make_zettelkasten_node())
    graph.add_node(NodeName.PERSIST, persist_artifacts)

    graph.add_edge(START, NodeName.VAULT_PROFILER)
    graph.add_edge(NodeName.VAULT_PROFILER, NodeName.RESEARCHER)
    graph.add_edge(NodeName.RESEARCHER, NodeName.SUMMARIZER)
    graph.add_edge(NodeName.SUMMARIZER, NodeName.ZETTELKASTEN)
    graph.add_edge(NodeName.ZETTELKASTEN, NodeName.PERSIST)
    graph.add_edge(NodeName.PERSIST, END)
    return graph


def _make_zettelkasten_node():
    """Build a zettelkasten node that prepends the vault profile as a system message.

    The zettelkasten agent's static system prompt instructs it to look
    for a ``<vault_profile>`` block in the first system message. That
    block is produced by the upstream ``vault_profiler`` node and
    written to ``state.vault_profile``. We don't pollute the shared
    message history — the SystemMessage is prepended only for this
    executor's invocation, not stored in graph state.
    """
    executor = build_agent_executor_from_spec(ZETTELKASTEN_SPEC)

    async def node(
        state: ResearchState,
        runtime: Runtime[ResearchContext],
        config: RunnableConfig,
    ) -> AgentRunResult:
        profile = state.get("vault_profile", "")
        if profile:
            augmented_messages = [
                SystemMessage(content=profile),
                *state["messages"],
            ]
            augmented_state: ResearchState = {
                **state,
                "messages": augmented_messages,
            }
        else:
            augmented_state = state
        return await run_agent_executor(
            executor,
            state=augmented_state,
            runtime_context=runtime.context,
            config=config,
            workflow_name=ZETTELKASTEN_SPEC.name,
        )

    node.__name__ = "zettelkasten_node"
    return node
