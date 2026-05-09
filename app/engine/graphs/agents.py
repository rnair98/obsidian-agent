"""Single-node workflow wrappers — exposes each agent as a runnable workflow."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.constants import END, START
from langgraph.graph import StateGraph

from app.engine.agents.researcher import SPEC as RESEARCHER_SPEC
from app.engine.agents.spec import AgentSpec
from app.engine.agents.summarizer import SPEC as SUMMARIZER_SPEC
from app.engine.agents.zettelkasten import SPEC as ZETTELKASTEN_SPEC
from app.engine.nodes.agent import make_agent_node
from app.engine.nodes.types import NodeName, WorkflowName
from app.engine.registry import workflow
from app.engine.schema import ResearchContext, ResearchState

if TYPE_CHECKING:
    from langgraph.checkpoint.memory import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph


def _single_node_graph(
    node_name: NodeName,
    spec: AgentSpec,
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    graph = StateGraph[
        ResearchState,
        ResearchContext,
        ResearchState,
        ResearchState,
    ](ResearchState)
    graph.add_node(node_name, make_agent_node(spec))
    graph.add_edge(START, node_name)
    graph.add_edge(node_name, END)
    return graph.compile(checkpointer=checkpointer)


@workflow(WorkflowName.RESEARCHER)
def create_researcher_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    return _single_node_graph(NodeName.RESEARCHER, RESEARCHER_SPEC, checkpointer)


@workflow(WorkflowName.SUMMARIZER)
def create_summarizer_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
    return _single_node_graph(NodeName.SUMMARIZER, SUMMARIZER_SPEC, checkpointer)


@workflow(WorkflowName.ZETTELKASTEN)
def create_zettelkasten_workflow(
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    return _single_node_graph(NodeName.ZETTELKASTEN, ZETTELKASTEN_SPEC, checkpointer)
