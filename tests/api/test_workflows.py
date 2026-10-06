"""API-level smoke tests for /workflows endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.settings import settings
from app.main import app

TEST_TOKEN = "workflow-test-token-not-a-production-secret"


@pytest.fixture(autouse=True)
def configured_access(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.security, "workflow_token", SecretStr(TEST_TOKEN))


def client() -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {TEST_TOKEN}"})


def test_node_only_name_rejected_at_validation() -> None:
    """``persist`` is a node, not a WorkflowName; the route must 422 it
    at request validation rather than 404 from the registry.
    """
    resp = client().post(
        "/api/v1/workflows/run/persist",
        json={"topic": "routing-test"},
    )
    assert resp.status_code == 422


def test_unknown_enum_value_returns_422() -> None:
    """A value outside WorkflowName should fail at request validation."""
    resp = client().post(
        "/api/v1/workflows/run/not-a-real-workflow",
        json={"topic": "enum-validation"},
    )
    assert resp.status_code == 422


def test_legacy_search_request_field_rejected() -> None:
    resp = client().post(
        "/api/v1/workflows/run/research",
        json={"topic": "routing-test", "search": {"raw": "old custom search"}},
    )
    assert resp.status_code == 422


def test_local_vault_request_shape_accepted_until_execution() -> None:
    resp = client().post(
        "/api/v1/workflows/run/not-a-real-workflow",
        json={
            "topic": "vault schema",
            "vault": {"type": "local", "path": "/tmp/test-vault"},
        },
    )

    # The workflow enum should be the only validation failure; the request
    # body shape itself is accepted by ResearchRequest.
    assert resp.status_code == 422
    assert "workflow_name" in resp.text
    assert "vault" not in resp.text


def test_inaccessible_git_vault_returns_400() -> None:
    resp = client().post(
        "/api/v1/workflows/run/research",
        json={
            "topic": "bad git vault",
            "vault": {
                "type": "git",
                "url": "/definitely/not/a/git/repo",
                "ref": "main",
            },
        },
    )

    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid vault configuration"}
    assert "definitely/not/a/git/repo" not in resp.text


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic abc"])
def test_unauthorized_request_never_executes(
    authorization: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Unauthorized request reached workflow execution")

    monkeypatch.setattr("app.api.v1.workflows.execute", forbidden)
    headers = {"Authorization": authorization} if authorization else {}
    response = TestClient(app).post(
        "/api/v1/workflows/run/research",
        headers=headers,
        json={"topic": "authorization", "vault": {"type": "local", "path": "/tmp/no"}},
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_missing_server_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.security, "workflow_token", SecretStr(""))
    response = client().post(
        "/api/v1/workflows/run/research",
        json={"topic": "authorization", "vault": {"type": "local", "path": "/tmp/no"}},
    )
    assert response.status_code == 503


def test_authorized_request_reaches_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.engine.vaults import VaultResolutionError

    called = []

    async def observed(*args: object) -> None:
        called.append(args)
        raise VaultResolutionError("Test stops before side effects")

    monkeypatch.setattr("app.api.v1.workflows.execute", observed)
    response = client().post(
        "/api/v1/workflows/run/research",
        json={"topic": "authorization", "vault": {"type": "local", "path": "/tmp/no"}},
    )
    assert response.status_code == 400
    assert len(called) == 1
