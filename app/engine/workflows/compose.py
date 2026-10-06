from collections.abc import Sequence

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.constants import END, START
from langgraph.graph.state import CompiledStateGraph, StateGraph


def compose_graphs(
    parts: Sequence[tuple[str, StateGraph]],
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    if not parts:
        raise ValueError("a workflow must include at least one graph")
    if len(parts) == 1:
        name, graph = parts[0]
        return graph.compile(checkpointer=checkpointer, name=name)
    first = parts[0][1]
    parent: StateGraph = StateGraph(
        first.state_schema,
        context_schema=first.context_schema,
    )
    previous = START
    for name, graph in parts:
        parent.add_node(name, graph.compile(name=name))
        parent.add_edge(previous, name)
        previous = name
    parent.add_edge(previous, END)
    return parent.compile(checkpointer=checkpointer)
