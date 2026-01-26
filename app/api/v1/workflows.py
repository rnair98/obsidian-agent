from fastapi import APIRouter, HTTPException

from app.engine.executor import execute
from app.engine.registry import list_workflows
from app.engine.schema import ResearchRequest

router = APIRouter()


@router.get("/workflows")
def get_workflows() -> list[str]:
    """
    Get a list of all registered workflows.
    """
    return list_workflows()


@router.post("/workflows/{workflow_name}/run")
def run_workflow(workflow_name: str, request: ResearchRequest) -> dict[str, object]:
    """
    Run a registered workflow with the given request.
    """
    try:
        return execute(workflow_name, request)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
