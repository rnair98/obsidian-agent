from collections.abc import Mapping

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.engine.nodes.connect import make_connect_node
from app.engine.nodes.types import NodeName
from app.engine.schema import ResearchContext, ResearchState


def build_connect_graph(
    *, prompt_context: Mapping[str, str] | None = None
) -> StateGraph:
    graph = StateGraph(ResearchState, context_schema=ResearchContext)
    graph.add_node(NodeName.CONNECT, make_connect_node(prompt_context=prompt_context))
    graph.add_edge(START, NodeName.CONNECT)
    graph.add_edge(NodeName.CONNECT, END)
    return graph
