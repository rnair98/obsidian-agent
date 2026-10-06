from pathlib import Path

import pytest
import yaml

from app.core.settings import Settings
from app.main import app


def test_nested_security_environment_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SECURITY__WORKFLOW_TOKEN", "configuration-test-value")
    monkeypatch.setenv("SECURITY__LOCAL_VAULTS", '["/approved/vault"]')
    monkeypatch.setenv("SECURITY__GIT_REPOSITORIES", '["https://github.com/o/r.git"]')
    config = Settings(_env_file=None)
    assert config.security.local_vaults == [Path("/approved/vault")]
    assert config.security.git_repositories == ["https://github.com/o/r.git"]
    assert (
        config.security.workflow_token.get_secret_value() == "configuration-test-value"
    )
    assert "configuration-test-value" not in repr(config.security)


def test_workflow_openapi_declares_bearer_authentication() -> None:
    operation = app.openapi()["paths"]["/api/v1/workflows/run/{workflow_name}"]["post"]
    assert operation["security"] == [{"HTTPBearer": []}]


def test_development_compose_does_not_publish_database_or_collector() -> None:
    root = Path(__file__).resolve().parents[2]
    services = yaml.safe_load((root / "docker-compose.yaml").read_text())["services"]
    assert "ports" not in services["db"]
    assert services["app"]["ports"] == ["127.0.0.1:8000:8000"]
    assert services["phoenix"]["ports"] == ["127.0.0.1:6006:6006"]
    assert (
        "POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD}"
        in services["db"]["environment"]
    )
