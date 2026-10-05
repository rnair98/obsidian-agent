from collections.abc import Mapping

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.engine.agents.researcher import SPEC as RESEARCHER_SPEC
from app.engine.agents.spec import AgentSpec
from app.engine.agents.summarizer import SPEC as SUMMARIZER_SPEC
from app.engine.agents.zettelkasten import SPEC as ZETTELKASTEN_SPEC
from app.engine.graphs.agents import build_agent_graph
from app.engine.nodes.types import NodeName, WorkflowName
from app.engine.registry import workflow
from app.engine.workflows.compose import compose_graphs


def _single_agent(
    name: NodeName,
    spec: AgentSpec,
    checkpointer: BaseCheckpointSaver,
    prompt_context: Mapping[str, str] | None,
):
    graph = build_agent_graph(name, spec, prompt_context=prompt_context)
    return compose_graphs(((name, graph),), checkpointer)


@workflow(WorkflowName.RESEARCHER)
def create_researcher_workflow(
    checkpointer: BaseCheckpointSaver,
    *,
    prompt_context: Mapping[str, str] | None = None,
):
    return _single_agent(
        NodeName.RESEARCHER, RESEARCHER_SPEC, checkpointer, prompt_context
    )


@workflow(WorkflowName.SUMMARIZER)
def create_summarizer_workflow(
    checkpointer: BaseCheckpointSaver,
    *,
    prompt_context: Mapping[str, str] | None = None,
):
    return _single_agent(
        NodeName.SUMMARIZER, SUMMARIZER_SPEC, checkpointer, prompt_context
    )


@workflow(WorkflowName.ZETTELKASTEN)
def create_zettelkasten_workflow(
    checkpointer: BaseCheckpointSaver,
    *,
    prompt_context: Mapping[str, str] | None = None,
):
    return _single_agent(
        NodeName.ZETTELKASTEN, ZETTELKASTEN_SPEC, checkpointer, prompt_context
    )
