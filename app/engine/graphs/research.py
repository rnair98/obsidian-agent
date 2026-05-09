from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.constants import END, START
from langgraph.graph.state import StateGraph

from app.engine.agents.researcher import SPEC as RESEARCHER_SPEC
from app.engine.agents.summarizer import SPEC as SUMMARIZER_SPEC
from app.engine.agents.zettelkasten import SPEC as ZETTELKASTEN_SPEC
from app.engine.nodes.agent import make_agent_node
from app.engine.nodes.persist import persist_artifacts
from app.engine.nodes.types import NodeName, WorkflowName
from app.engine.registry import workflow
from app.engine.schema import ResearchContext, ResearchState

if TYPE_CHECKING:
    from langgraph.checkpoint.memory import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph


@workflow(WorkflowName.RESEARCH)
def create_research_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    graph = StateGraph[
        ResearchState,
        ResearchContext,
        ResearchState,
        ResearchState,
    ](ResearchState)

    graph.add_node(
        NodeName.RESEARCHER, make_agent_node(RESEARCHER_SPEC, log_streams=True)
    )
    graph.add_node(NodeName.SUMMARIZER, make_agent_node(SUMMARIZER_SPEC))
    graph.add_node(NodeName.ZETTELKASTEN, make_agent_node(ZETTELKASTEN_SPEC))
    graph.add_node(NodeName.PERSIST, persist_artifacts)

    graph.add_edge(START, NodeName.RESEARCHER)
    graph.add_edge(NodeName.RESEARCHER, NodeName.SUMMARIZER)
    graph.add_edge(NodeName.SUMMARIZER, NodeName.ZETTELKASTEN)
    graph.add_edge(NodeName.ZETTELKASTEN, NodeName.PERSIST)
    graph.add_edge(NodeName.PERSIST, END)
    return graph.compile(checkpointer=checkpointer)
