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
