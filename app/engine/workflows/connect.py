from collections.abc import Mapping

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.engine.graphs.connect import build_connect_graph
from app.engine.nodes.types import WorkflowName
from app.engine.registry import workflow
from app.engine.workflows.compose import compose_graphs


@workflow(WorkflowName.CONNECT)
def create_connect_workflow(
    checkpointer: BaseCheckpointSaver,
    *,
    prompt_context: Mapping[str, str] | None = None,
):
    return compose_graphs(
        (("connect", build_connect_graph(prompt_context=prompt_context)),), checkpointer
    )
