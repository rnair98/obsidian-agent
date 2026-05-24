from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.runnables import Runnable
from langgraph.checkpoint.base import BaseCheckpointSaver

WorkflowFactory = Callable[
    ...,
    Runnable[Any, Any],
]

_WORKFLOW_REGISTRY: dict[str, WorkflowFactory] = {}


def workflow(name: str) -> Callable[[WorkflowFactory], WorkflowFactory]:
    """
    Decorator to register a workflow factory function.

    Usage:
        @workflow("my-workflow")
        def create_my_workflow(
            checkpointer: BaseCheckpointSaver[Any],
        ) -> Runnable[Any, Any]:
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
    checkpointer: BaseCheckpointSaver[Any],
    **factory_kwargs: Any,
) -> Runnable[Any, Any]:
    """Retrieve a compiled workflow graph by name.

    Additional keyword arguments are forwarded to the registered factory.
    Workflows are built per-request, so passing per-request context here
    (e.g. ``prompt_context={"prior_memories": ...}``) is the supported
    seam for injecting request-scoped data into agent prompts.
    """
    if name not in _WORKFLOW_REGISTRY:
        raise ValueError(f"Workflow '{name}' not found. Available: {list_workflows()}")
    return _WORKFLOW_REGISTRY[name](checkpointer, **factory_kwargs)
