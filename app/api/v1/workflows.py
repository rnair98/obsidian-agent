from fastapi import APIRouter

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
    return await execute(workflow_name, request)
