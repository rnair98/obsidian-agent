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
from app.engine.nodes.types import NodeName
from app.engine.nodes.zettelkasten import create_zettelkasten_agent
from app.engine.registry import workflow
from app.engine.schema import ResearchContext, ResearchState


@workflow(NodeName.RESEARCHER)
def create_researcher_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    graph = StateGraph[
        ResearchState,
        ResearchContext,
        ResearchState,
        ResearchState,
    ](ResearchState)
    graph.add_node(NodeName.RESEARCHER, create_researcher_agent())
    graph.add_edge(START, NodeName.RESEARCHER)
    graph.add_edge(NodeName.RESEARCHER, END)
    return graph.compile(checkpointer=checkpointer)


@workflow(NodeName.SUMMARIZER)
def create_summarizer_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    graph = StateGraph[
        ResearchState,
        ResearchContext,
        ResearchState,
        ResearchState,
    ](ResearchState)
    graph.add_node(NodeName.SUMMARIZER, create_summarizer_agent())
    graph.add_edge(START, NodeName.SUMMARIZER)
    graph.add_edge(NodeName.SUMMARIZER, END)
    return graph.compile(checkpointer=checkpointer)


@workflow(NodeName.ZETTELKASTEN)
def create_zettelkasten_workflow(
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    graph = StateGraph[
        ResearchState,
        None,
        ResearchState,
        ResearchState,
    ](ResearchState)
    graph.add_node(NodeName.ZETTELKASTEN, create_zettelkasten_agent())
    graph.add_edge(START, NodeName.ZETTELKASTEN)
    graph.add_edge(NodeName.ZETTELKASTEN, END)
    return graph.compile(checkpointer=checkpointer)
