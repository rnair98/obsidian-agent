from collections.abc import Mapping

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.engine.graphs.research import build_research_graph
from app.engine.nodes.types import WorkflowName
from app.engine.registry import workflow
from app.engine.workflows.compose import compose_graphs


@workflow(WorkflowName.RESEARCH)
def create_research_workflow(
    checkpointer: BaseCheckpointSaver,
    *,
    prompt_context: Mapping[str, str] | None = None,
):
    return compose_graphs(
        (("research", build_research_graph(prompt_context=prompt_context)),),
        checkpointer,
    )
