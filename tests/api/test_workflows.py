"""API-level smoke tests for /workflows endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_unregistered_workflow_returns_404() -> None:
    """The Workflow enum admits 'persist' (a node, not an invocable
    workflow); the endpoint must translate get_workflow's ValueError into
    an HTTP 404 rather than a 500.
    """
    client = TestClient(app)
    resp = client.post(
        "/api/v1/workflows/run/persist",
        json={"topic": "routing-test"},
    )
    assert resp.status_code == 404
    assert "persist" in resp.json()["detail"].lower()


def test_unknown_enum_value_returns_422() -> None:
    """A value outside the Workflow enum should fail at request validation."""
    client = TestClient(app)
    resp = client.post(
        "/api/v1/workflows/run/not-a-real-workflow",
        json={"topic": "enum-validation"},
    )
    assert resp.status_code == 422
