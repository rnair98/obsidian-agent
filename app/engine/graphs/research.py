from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.constants import END, START
from langgraph.graph.state import StateGraph

from app.engine.nodes.persist import persist_artifacts
from app.engine.nodes.researcher import create_researcher_agent
from app.engine.nodes.summarizer import create_summarizer_agent
from app.engine.nodes.zettelkasten import create_zettelkasten_agent
from app.engine.registry import workflow
from app.engine.schema import ResearchState

if TYPE_CHECKING:
    from langgraph.checkpoint.memory import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph


def build_research_graph() -> StateGraph[ResearchState]:
    graph = StateGraph(ResearchState)

    # Instantiate agents
    researcher = create_researcher_agent()
    summarizer = create_summarizer_agent()
    zettelkasten = create_zettelkasten_agent()

    graph.add_node("researcher", researcher)
    graph.add_node("summarizer", summarizer)
    graph.add_node("zettelkasten", zettelkasten)
    graph.add_node("persist", persist_artifacts)

    graph.add_edge(START, "researcher")
    graph.add_edge("researcher", "summarizer")
    graph.add_edge("summarizer", "zettelkasten")
    graph.add_edge("zettelkasten", "persist")
    graph.add_edge("persist", END)
    return graph


@workflow("research")
def create_research_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    return build_research_graph().compile(checkpointer=checkpointer)
