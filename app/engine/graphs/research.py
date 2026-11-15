from __future__ import annotations

from collections.abc import Mapping

from langgraph.constants import END, START
from langgraph.graph.state import StateGraph

from app.engine.agents.researcher import SPEC as RESEARCHER_SPEC
from app.engine.agents.summarizer import SPEC as SUMMARIZER_SPEC
from app.engine.agents.zettelkasten import SPEC as ZETTELKASTEN_SPEC
from app.engine.nodes.agent import make_agent_node
from app.engine.nodes.persist import persist_artifacts
from app.engine.nodes.types import NodeName
from app.engine.schema import ResearchContext, ResearchState


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

    graph.add_node(
        NodeName.RESEARCHER,
        make_agent_node(
            RESEARCHER_SPEC, log_streams=True, prompt_context=prompt_context
        ),
    )
    graph.add_node(NodeName.SUMMARIZER, make_agent_node(SUMMARIZER_SPEC))
    graph.add_node(NodeName.ZETTELKASTEN, make_agent_node(ZETTELKASTEN_SPEC))
    graph.add_node(NodeName.PERSIST, persist_artifacts)

    graph.add_edge(START, NodeName.RESEARCHER)
    graph.add_edge(NodeName.RESEARCHER, NodeName.SUMMARIZER)
    graph.add_edge(NodeName.SUMMARIZER, NodeName.ZETTELKASTEN)
    graph.add_edge(NodeName.ZETTELKASTEN, NodeName.PERSIST)
    graph.add_edge(NodeName.PERSIST, END)
    return graph
