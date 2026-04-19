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
from app.engine.nodes.types import Workflow
from app.engine.nodes.zettelkasten import create_zettelkasten_agent
from app.engine.registry import workflow
from app.engine.schema import ResearchContext, ResearchState


@workflow(Workflow.RESEARCHER)
def create_researcher_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    graph = StateGraph[
        ResearchState,
        ResearchContext,
        ResearchState,
        ResearchState,
    ](ResearchState)
    graph.add_node(Workflow.RESEARCHER, create_researcher_agent())
    graph.add_edge(START, Workflow.RESEARCHER)
    graph.add_edge(Workflow.RESEARCHER, END)
    return graph.compile(checkpointer=checkpointer)


@workflow(Workflow.SUMMARIZER)
def create_summarizer_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    graph = StateGraph[
        ResearchState,
        ResearchContext,
        ResearchState,
        ResearchState,
    ](ResearchState)
    graph.add_node(Workflow.SUMMARIZER, create_summarizer_agent())
    graph.add_edge(START, Workflow.SUMMARIZER)
    graph.add_edge(Workflow.SUMMARIZER, END)
    return graph.compile(checkpointer=checkpointer)


@workflow(Workflow.ZETTELKASTEN)
def create_zettelkasten_workflow(
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    graph = StateGraph[
        ResearchState,
        None,
        ResearchState,
        ResearchState,
    ](ResearchState)
    graph.add_node(Workflow.ZETTELKASTEN, create_zettelkasten_agent())
    graph.add_edge(START, Workflow.ZETTELKASTEN)
    graph.add_edge(Workflow.ZETTELKASTEN, END)
    return graph.compile(checkpointer=checkpointer)
