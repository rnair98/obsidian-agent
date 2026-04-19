from fastapi import APIRouter, HTTPException

from app.engine.executor import execute
from app.engine.nodes.types import Workflow
from app.engine.schema import ResearchRequest

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
)


@router.post("/run/{workflow_name}")
async def run_workflow(
    workflow_name: Workflow,
    request: ResearchRequest,
) -> dict[str, object]:
    try:
        return await execute(workflow_name, request)
    except ValueError as exc:
        # get_workflow raises ValueError for unregistered names. The Workflow
        # enum admits values (e.g. "persist") that aren't registered as
        # invocable workflows, so this happens for well-formed URLs.
        raise HTTPException(status_code=404, detail=str(exc)) from exc
