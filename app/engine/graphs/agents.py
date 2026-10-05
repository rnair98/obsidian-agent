from __future__ import annotations

from typing import Any

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.engine.agents.spec import AgentSpec
from app.engine.nodes.agent import make_agent_node
from app.engine.nodes.types import NodeName
from app.engine.schema import ResearchContext


def build_agent_graph(node_name: NodeName, spec: AgentSpec) -> StateGraph:
    graph = StateGraph[
        Any,
        ResearchContext,
        Any,
        Any,
    ](state_schema=Any)
    graph.add_node(node_name, action=make_agent_node(spec))
    graph.add_edge(START, node_name)
    graph.add_edge(node_name, END)
    return graph
