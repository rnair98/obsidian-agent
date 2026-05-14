"""API-level smoke tests for /workflows endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_node_only_name_rejected_at_validation() -> None:
    """``persist`` is a node, not a WorkflowName; the route must 422 it
    at request validation rather than 404 from the registry.
    """
    client = TestClient(app)
    resp = client.post(
        "/api/v1/workflows/run/persist",
        json={"topic": "routing-test"},
    )
    assert resp.status_code == 422


def test_unknown_enum_value_returns_422() -> None:
    """A value outside WorkflowName should fail at request validation."""
    client = TestClient(app)
    resp = client.post(
        "/api/v1/workflows/run/not-a-real-workflow",
        json={"topic": "enum-validation"},
    )
    assert resp.status_code == 422


def test_legacy_search_request_field_rejected() -> None:
    client = TestClient(app)
    resp = client.post(
        "/api/v1/workflows/run/research",
        json={"topic": "routing-test", "search": {"raw": "old custom search"}},
    )
    assert resp.status_code == 422


def test_local_vault_request_shape_accepted_until_execution() -> None:
    client = TestClient(app)
    resp = client.post(
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
    client = TestClient(app)
    resp = client.post(
        "/api/v1/workflows/run/research",
        json={
            "topic": "bad git vault",
            "vault": {"type": "git", "url": "/definitely/not/a/git/repo"},
        },
    )

    assert resp.status_code == 400
    assert resp.json() == {"detail": "Invalid vault configuration"}
    assert "definitely/not/a/git/repo" not in resp.text
