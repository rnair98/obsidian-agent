from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.constants import END, START
from langgraph.graph.state import StateGraph

from app.engine.nodes.persist import persist_artifacts
from app.engine.nodes.researcher import create_researcher_agent
from app.engine.nodes.summarizer import create_summarizer_agent
from app.engine.nodes.types import Workflow
from app.engine.nodes.zettelkasten import create_zettelkasten_agent
from app.engine.registry import workflow
from app.engine.schema import ResearchContext, ResearchState

if TYPE_CHECKING:
    from langgraph.checkpoint.memory import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph


@workflow(Workflow.RESEARCH)
def create_research_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    graph = StateGraph[
        ResearchState,
        ResearchContext,
        ResearchState,
        ResearchState,
    ](ResearchState)

    # Instantiate agents
    researcher = create_researcher_agent()
    summarizer = create_summarizer_agent()
    zettelkasten = create_zettelkasten_agent()

    graph.add_node(Workflow.RESEARCHER, researcher)
    graph.add_node(Workflow.SUMMARIZER, summarizer)
    graph.add_node(Workflow.ZETTELKASTEN, zettelkasten)
    graph.add_node(Workflow.PERSIST, persist_artifacts)

    graph.add_edge(START, Workflow.RESEARCHER)
    graph.add_edge(Workflow.RESEARCHER, Workflow.SUMMARIZER)
    graph.add_edge(Workflow.SUMMARIZER, Workflow.ZETTELKASTEN)
    graph.add_edge(Workflow.ZETTELKASTEN, Workflow.PERSIST)
    graph.add_edge(Workflow.PERSIST, END)
    return graph.compile(checkpointer=checkpointer)
