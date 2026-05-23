from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.schema import ResearchRequest
from app.engine.vaults import VaultResolutionError, resolve_vault


def test_research_request_accepts_local_vault_object(tmp_path: Path) -> None:
    request = ResearchRequest.model_validate(
        {
            "topic": "vault routing",
            "vault": {"type": "local", "path": str(tmp_path / "Knowledge")},
        }
    )

    assert request.vault is not None
    assert request.vault.type == "local"
    assert request.vault.path == tmp_path / "Knowledge"


def test_research_request_accepts_git_vault_object() -> None:
    request = ResearchRequest.model_validate(
        {
            "topic": "remote vault",
            "vault": {
                "type": "git",
                "url": "https://github.com/example/vault.git",
                "ref": "main",
            },
        }
    )

    assert request.vault is not None
    assert request.vault.type == "git"
    assert request.vault.url == "https://github.com/example/vault.git"
    assert request.vault.ref == "main"


def test_research_request_rejects_unknown_vault_type() -> None:
    with pytest.raises(ValueError):
        ResearchRequest.model_validate(
            {"topic": "bad vault", "vault": {"type": "s3", "bucket": "x"}}
        )


def test_local_vault_resolver_preserves_existing_vault_content(tmp_path: Path) -> None:
    vault_path = tmp_path / "Vault"
    backend = InProcessFilesystemBackend(vault_path)
    backend.write_text("Existing.md", "# Existing")

    layout = resolve_vault(
        ResearchRequest(
            topic="local vault",
            vault={"type": "local", "path": str(vault_path)},
        )
    )

    assert layout.backend.read_text("Existing.md") == "# Existing"
    assert layout.backend.is_dir(".obsidian")
    assert layout.backend.is_dir("notes")


def test_git_vault_resolver_clones_to_managed_writable_vault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = tmp_path / "remote-vault"
    remote.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=remote, check=True, capture_output=True
    )
    (remote / "Remote.md").write_text("# Remote", encoding="utf-8")
    subprocess.run(["git", "add", "Remote.md"], cwd=remote, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "init",
        ],
        cwd=remote,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr("app.core.settings.settings.filesystem.base_path", tmp_path)

    layout = resolve_vault(
        ResearchRequest(
            topic="git vault",
            vault={"type": "git", "url": str(remote), "ref": "main"},
        )
    )

    assert layout.backend.read_text("Remote.md") == "# Remote"
    assert layout.backend.is_dir(".obsidian")
    assert layout.backend.is_dir("notes")
    layout.backend.write_text("notes/local.md", "local write")
    assert layout.backend.read_text("notes/local.md") == "local write"
    assert (tmp_path / ".vaults").is_dir()


def test_git_vault_resolver_rejects_option_shaped_operands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.core.settings.settings.filesystem.base_path", tmp_path)

    with pytest.raises(VaultResolutionError, match="url must not start"):
        resolve_vault(
            ResearchRequest(
                topic="git vault",
                vault={"type": "git", "url": "--upload-pack=bad", "ref": "main"},
            )
        )

    with pytest.raises(VaultResolutionError, match="ref must not start"):
        resolve_vault(
            ResearchRequest(
                topic="git vault",
                vault={
                    "type": "git",
                    "url": "https://github.com/example/vault.git",
                    "ref": "-bad",
                },
            )
        )
