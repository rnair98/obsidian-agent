from fastapi import APIRouter

from app.engine.executor import execute
from app.engine.schema import ResearchRequest

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
)


@router.post("/run/{workflow_name}")
def run_workflow(workflow_name: str, request: ResearchRequest) -> dict[str, object]:
    return execute(workflow_name, request)
