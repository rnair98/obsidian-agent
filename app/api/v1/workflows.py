from fastapi import APIRouter, HTTPException

from app.engine.executor import execute
from app.engine.nodes.types import WorkflowName
from app.engine.schema import ResearchRequest, WorkflowRunResponse
from app.engine.vaults import VaultResolutionError

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
)


@router.post("/run/{workflow_name}", response_model=WorkflowRunResponse)
async def run_workflow(
    workflow_name: WorkflowName,
    request: ResearchRequest,
) -> WorkflowRunResponse:
    """Execute a registered workflow and return references to its artifacts.

    The 200 OK body is a :class:`WorkflowRunResponse` — a typed projection of
    the final ``ResearchState`` that points clients at every durable artifact
    the workflow materialized in the vault (report, sources CSV, Zettel
    notes, memory file) plus the LangGraph ``run_id`` for checkpoint replay.
    The raw state is intentionally NOT exposed; it carries internal LangGraph
    plumbing and noisy per-node accumulators.
    """
    try:
        return await execute(workflow_name, request)
    except VaultResolutionError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid vault configuration",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
