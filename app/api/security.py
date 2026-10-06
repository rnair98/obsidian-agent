"""Authentication for operations that consume compute or filesystem authority."""

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.settings import settings

_bearer = HTTPBearer(auto_error=False)


def require_workflow_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    expected = settings.security.workflow_token.get_secret_value()
    if not expected:
        raise HTTPException(503, "Workflow access is not configured")
    if credentials is None or not secrets.compare_digest(
        credentials.credentials.encode("utf-8"), expected.encode("utf-8")
    ):
        raise HTTPException(
            401, "Invalid workflow credentials", headers={"WWW-Authenticate": "Bearer"}
        )
