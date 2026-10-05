from langgraph.checkpoint.base import BaseCheckpointSaver

from app.engine.agents.researcher import SPEC as RESEARCHER_SPEC
from app.engine.agents.summarizer import SPEC as SUMMARIZER_SPEC
from app.engine.agents.zettelkasten import SPEC as ZETTELKASTEN_SPEC
from app.engine.graphs.agents import build_agent_graph
from app.engine.nodes.types import NodeName, WorkflowName
from app.engine.registry import workflow
from app.engine.workflows.compose import compose_graphs


@workflow(WorkflowName.RESEARCHER)
def create_researcher_workflow(checkpointer: BaseCheckpointSaver):
    return compose_graphs(
        (
            (
                NodeName.RESEARCHER,
                build_agent_graph(NodeName.RESEARCHER, RESEARCHER_SPEC),
            ),
        ),
        checkpointer,
    )


@workflow(WorkflowName.SUMMARIZER)
def create_summarizer_workflow(checkpointer: BaseCheckpointSaver):
    return compose_graphs(
        (
            (
                NodeName.SUMMARIZER,
                build_agent_graph(NodeName.SUMMARIZER, SUMMARIZER_SPEC),
            ),
        ),
        checkpointer,
    )


@workflow(WorkflowName.ZETTELKASTEN)
def create_zettelkasten_workflow(checkpointer: BaseCheckpointSaver):
    return compose_graphs(
        (
            (
                NodeName.ZETTELKASTEN,
                build_agent_graph(NodeName.ZETTELKASTEN, ZETTELKASTEN_SPEC),
            ),
        ),
        checkpointer,
    )
