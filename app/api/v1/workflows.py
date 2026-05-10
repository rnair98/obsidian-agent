from fastapi import APIRouter, HTTPException

from app.engine.executor import execute
from app.engine.nodes.types import WorkflowName
from app.engine.schema import ResearchRequest

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
)


@router.post("/run/{workflow_name}")
async def run_workflow(
    workflow_name: WorkflowName,
    request: ResearchRequest,
) -> dict[str, object]:
    try:
        return await execute(workflow_name, request)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
