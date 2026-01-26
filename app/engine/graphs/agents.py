"""
Single-agent workflow wrappers.

Each agent can be run standalone as a workflow.
"""

from langgraph.checkpoint.memory import BaseCheckpointSaver
from langgraph.constants import END, START
from langgraph.graph import StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.engine.nodes.researcher import create_researcher_agent
from app.engine.nodes.summarizer import create_summarizer_agent
from app.engine.nodes.zettelkasten import create_zettelkasten_agent
from app.engine.registry import workflow
from app.engine.schema import ResearchState


@workflow("researcher")
def create_researcher_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    graph = StateGraph(ResearchState)
    graph.add_node("researcher", create_researcher_agent())
    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", END)
    return graph.compile(checkpointer=checkpointer)


@workflow("summarizer")
def create_summarizer_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    graph = StateGraph(ResearchState)
    graph.add_node("summarizer", create_summarizer_agent())
    graph.add_edge(START, "summarizer")
    graph.add_edge("summarizer", END)
    return graph.compile(checkpointer=checkpointer)


@workflow("zettelkasten")
def create_zettelkasten_workflow(
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    graph = StateGraph(ResearchState)
    graph.add_node("zettelkasten", create_zettelkasten_agent())
    graph.add_edge(START, "zettelkasten")
    graph.add_edge("zettelkasten", END)
    return graph.compile(checkpointer=checkpointer)
