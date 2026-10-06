from __future__ import annotations

from collections.abc import Mapping

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.engine.agents.spec import AgentSpec
from app.engine.nodes.agent import make_agent_node
from app.engine.nodes.types import NodeName
from app.engine.schema import ResearchContext, ResearchState


def build_agent_graph(
    node_name: NodeName,
    spec: AgentSpec,
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
        node_name, action=make_agent_node(spec, prompt_context=prompt_context)
    )
    graph.add_edge(START, node_name)
    graph.add_edge(node_name, END)
    return graph
