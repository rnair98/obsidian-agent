from __future__ import annotations

from collections.abc import Callable

from langgraph.checkpoint.memory import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

WorkflowFactory = Callable[[BaseCheckpointSaver], CompiledStateGraph]

# Global registry: name -> factory function
_WORKFLOW_REGISTRY: dict[str, WorkflowFactory] = {}


def workflow(name: str) -> Callable[[WorkflowFactory], WorkflowFactory]:
    """
    Decorator to register a workflow factory function.

    Usage:
        @workflow("my-workflow")
        def create_my_workflow(checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
            ...
    """

    def decorator(fn: WorkflowFactory) -> WorkflowFactory:
        _WORKFLOW_REGISTRY[name] = fn
        return fn

    return decorator


def list_workflows() -> list[str]:
    """List all registered workflow names."""
    return list(_WORKFLOW_REGISTRY.keys())


def get_workflow(
    name: str,
    checkpointer: BaseCheckpointSaver,
) -> CompiledStateGraph:
    """Retrieve a compiled workflow graph by name."""
    if name not in _WORKFLOW_REGISTRY:
        raise ValueError(f"Workflow '{name}' not found. Available: {list_workflows()}")
    return _WORKFLOW_REGISTRY[name](checkpointer)
