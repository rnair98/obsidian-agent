from typing import Callable

from langgraph.graph.state import CompiledStateGraph

# Global registry: name -> factory function
_WORKFLOW_REGISTRY: dict[str, Callable[[], CompiledStateGraph]] = {}


def workflow(name: str):
    """
    Decorator to register a workflow factory function.

    Usage:
        @workflow("my-workflow")
        def create_my_workflow() -> CompiledStateGraph:
            ...
    """

    def decorator(
        fn: Callable[[], CompiledStateGraph],
    ) -> Callable[[], CompiledStateGraph]:
        _WORKFLOW_REGISTRY[name.lower()] = fn
        return fn

    return decorator


def list_workflows() -> list[str]:
    """
    List all registered workflow names.
    """
    return list(_WORKFLOW_REGISTRY.keys())


def get_workflow(name: str) -> CompiledStateGraph:
    """
    Retrieve a compiled workflow graph by name.
    """
    name = name.lower()
    if name not in _WORKFLOW_REGISTRY:
        raise ValueError(f"Workflow '{name}' not found. Available: {list_workflows()}")
    return _WORKFLOW_REGISTRY[name]()
