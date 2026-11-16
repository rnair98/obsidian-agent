from fastapi import APIRouter, Depends, HTTPException

from app.api.security import require_workflow_token
from app.engine.connect import ConnectError, ConnectUnavailable
from app.engine.executor import execute
from app.engine.nodes.types import WorkflowName
from app.engine.schema import ResearchRequest, WorkflowRunResponse
from app.engine.vaults import VaultResolutionError

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
    dependencies=[Depends(require_workflow_token)],
)


@router.post("/run/{workflow_name}", response_model=WorkflowRunResponse)
async def run_workflow(
    workflow_name: WorkflowName,
    request: ResearchRequest,
) -> WorkflowRunResponse:
    """Execute a registered workflow and return references to its artifacts."""
    try:
        return await execute(workflow_name, request)
    except VaultResolutionError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid vault configuration",
        ) from exc
    except ConnectError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConnectUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
