from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.core.settings import settings
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


def test_research_request_rejects_blank_git_ref() -> None:
    with pytest.raises(ValueError):
        ResearchRequest.model_validate(
            {
                "topic": "remote vault",
                "vault": {
                    "type": "git",
                    "url": "https://github.com/example/vault.git",
                    "ref": "   ",
                },
            }
        )


def test_research_request_rejects_unknown_vault_type() -> None:
    with pytest.raises(ValueError):
        ResearchRequest.model_validate(
            {"topic": "bad vault", "vault": {"type": "s3", "bucket": "x"}}
        )


def test_local_vault_resolver_preserves_existing_vault_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault_path = tmp_path / "Vault"
    backend = InProcessFilesystemBackend(vault_path)
    backend.write_text("Existing.md", "# Existing")
    monkeypatch.setattr(settings.security, "local_vaults", [vault_path])

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
    url = "https://github.com/example/vault.git"
    calls = []
    from app.engine.vaults import _run_git

    def simulated_git(args: list[str]) -> str:
        calls.append(args)
        if args[0] == "config":
            return _run_git(args)
        if args[0] == "clone":
            target = Path(args[-1])
            subprocess.run(
                ["git", "init", "-b", "main", str(target)],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(target), "remote", "add", "origin", url],
                check=True,
                capture_output=True,
            )
            (target / "Remote.md").write_text("# Remote")
        return ""

    monkeypatch.setattr("app.core.settings.settings.filesystem.base_path", tmp_path)
    monkeypatch.setattr(settings.security, "git_repositories", [url])
    monkeypatch.setattr("app.engine.vaults._run_git", simulated_git)

    layout = resolve_vault(
        ResearchRequest(
            topic="git vault",
            vault={"type": "git", "url": url, "ref": "main"},
        )
    )

    assert layout.backend.read_text("Remote.md") == "# Remote"
    assert layout.backend.is_dir(".obsidian")
    assert layout.backend.is_dir("notes")
    layout.backend.write_text("notes/local.md", "local write")
    assert layout.backend.read_text("notes/local.md") == "local write"
    assert (tmp_path / ".vaults").is_dir()
    # Existing vaults keep local notes and fetch only the approved URL.
    resolve_vault(
        ResearchRequest(
            topic="git vault", vault={"type": "git", "url": url, "ref": "main"}
        )
    )
    assert calls[-2][2:] == ["fetch", "--", url, "main"]
    assert layout.backend.read_text("notes/local.md") == "local write"


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


def test_local_vault_default_denial_has_no_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings.security, "local_vaults", [])
    target = tmp_path / "not-approved"
    with pytest.raises(VaultResolutionError, match="not approved"):
        resolve_vault(
            ResearchRequest(
                topic="denied path", vault={"type": "local", "path": str(target)}
            )
        )
    assert not target.exists()


def test_approved_root_does_not_approve_children_or_symlinks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    approved = tmp_path / "approved"
    outside = tmp_path / "outside"
    outside.mkdir()
    approved.symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(settings.security, "local_vaults", [approved])
    for target in [approved, outside, approved / "child", Path("relative")]:
        with pytest.raises(VaultResolutionError):
            resolve_vault(
                ResearchRequest(
                    topic="denied alias", vault={"type": "local", "path": str(target)}
                )
            )
    assert not (outside / ".obsidian").exists()


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/example/vault.git",
        "https://github.com/other/vault.git",
        "https://127.0.0.1/vault.git",
        "https://github.com@127.0.0.1/vault.git",
        "http://github.com/example/vault.git",
        "file:///tmp/repo",
        "ssh://github.com/repo",
        "https://github.com/example/vault.git?redirect=bad",
        "ext::bad",
    ],
)
def test_git_default_denial_never_starts_process(
    url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings.security, "git_repositories", [])
    monkeypatch.setattr(settings.filesystem, "base_path", tmp_path)
    monkeypatch.setattr(
        "app.engine.vaults._run_git", lambda args: pytest.fail("Denied URL started git")
    )
    with pytest.raises(VaultResolutionError):
        resolve_vault(
            ResearchRequest(
                topic="denied git", vault={"type": "git", "url": url, "ref": "main"}
            )
        )
    assert not (tmp_path / ".vaults").exists()


def test_cached_url_rewrites_are_rejected(tmp_path: Path) -> None:
    from app.engine.vaults import _validate_cached_git_config

    config = tmp_path / ".git/config"
    config.parent.mkdir()
    config.write_text('[url "https://internal/"]\n\tinsteadOf = https://github.com/\n')
    with pytest.raises(VaultResolutionError, match="Unsafe"):
        _validate_cached_git_config(tmp_path, "https://github.com/example/vault.git")


def test_git_worker_does_not_inherit_network_or_credential_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.engine.vaults import _run_git

    observed = {}
    monkeypatch.setenv("HTTPS_PROXY", "http://untrusted-proxy")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_SSH_COMMAND", "untrusted")

    def record(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        observed.update(command=command, **kwargs)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("app.engine.vaults.subprocess.run", record)
    _run_git(["--version"])
    env = observed["env"]
    assert env["GIT_ALLOW_PROTOCOL"] == "https"
    assert env["GIT_CONFIG_GLOBAL"] == "/dev/null"
    assert not {"HTTPS_PROXY", "GIT_CONFIG_COUNT", "GIT_SSH_COMMAND"} & env.keys()
    assert "http.followRedirects=false" in observed["command"]
    assert "http.sslVerify=true" in observed["command"]


def test_git_option_shaped_ref_is_rejected() -> None:
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


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/example/vault.git",
        "https://127.0.0.1/vault.git",
        "file:///tmp/repo",
        "ssh://github.com/example/vault.git",
        "https://github.com/example/vault.git?query=bad",
        "https://github.com@example.invalid/example/vault.git",
    ],
)
def test_allowlist_cannot_enable_unsafe_git_transport(
    url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings.security, "git_repositories", [url])
    monkeypatch.setattr(
        "app.engine.vaults._run_git",
        lambda args: pytest.fail("Unsafe transport started"),
    )
    with pytest.raises(VaultResolutionError):
        resolve_vault(
            ResearchRequest(
                topic="unsafe transport",
                vault={"type": "git", "url": url, "ref": "main"},
            )
        )


def test_actual_git_worker_rejects_file_transport(tmp_path: Path) -> None:
    from app.engine.vaults import _run_git

    source = tmp_path / "source"
    subprocess.run(["git", "init", str(source)], check=True, capture_output=True)
    with pytest.raises(VaultResolutionError, match="operation failed"):
        _run_git(["clone", "--", str(source), str(tmp_path / "clone")])


def test_approved_local_vault_does_not_authorize_its_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings.security, "local_vaults", [tmp_path])
    child = tmp_path / "unapproved-child"
    with pytest.raises(VaultResolutionError, match="not approved"):
        resolve_vault(
            ResearchRequest(
                topic="unapproved child", vault={"type": "local", "path": str(child)}
            )
        )
    assert not child.exists()
