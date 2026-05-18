from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.engine.workspace_commands.git import GitCommand
from app.harness.session import WorkspaceSession
from app.services.gh_client.types import SnapshotResult


class _TreeEntry:
    def __init__(self, path: str) -> None:
        self.path = path


class _FakeRepo:
    full_name = "owner/repo"
    default_branch = "main"


class _FakeService:
    repo = _FakeRepo()

    def __init__(self, repo_name: str) -> None:
        self.repo_name = repo_name

    def get_tree(self) -> list[_TreeEntry]:
        return [_TreeEntry("README.md"), _TreeEntry("src/app.py")]

    def shallow_clone(self, ref: str | None = None) -> SnapshotResult:
        return SnapshotResult(
            repo_name="owner/repo",
            commit_sha="abc123",
            requested_ref=ref or "main",
            path=Path("owner/repo@abc123"),
            created_at=datetime.now(timezone.utc),
            skipped=False,
        )


def _service_factory(repo_name: str) -> Any:
    return _FakeService(repo_name)


def test_git_ls_tree_surfaces_github_tree_as_git_command() -> None:
    command = GitCommand(service_factory=_service_factory)
    session = WorkspaceSession.scratch()

    result = command(session, ["ls-tree", "-r", "owner/repo"])

    assert result.exit_code == 0
    assert result.stdout == "README.md\nsrc/app.py\n"


def test_git_clone_reports_virtual_repo_snapshot_path() -> None:
    command = GitCommand(service_factory=_service_factory)
    session = WorkspaceSession.scratch()

    result = command(session, ["clone", "owner/repo"])

    assert result.exit_code == 0
    assert "cloned owner/repo main abc123 to /repos/owner/repo@abc123" in result.stdout


def test_git_command_rejects_mutating_porcelain() -> None:
    command = GitCommand(service_factory=_service_factory)
    session = WorkspaceSession.scratch()

    result = command(session, ["push"])

    assert result.exit_code == 2
    assert result.stderr == (
        "git: unsupported command: push; supported forms: "
        "git ls-tree [-r] owner/repo; git clone owner/repo [ref]\n"
    )


def test_git_command_rejects_oversmart_show_command_with_supported_forms() -> None:
    command = GitCommand(service_factory=_service_factory)
    session = WorkspaceSession.scratch()

    result = command(session, ["show", "HEAD:README.md"])

    assert result.exit_code == 2
    assert "supported forms:" in result.stderr
    assert "git ls-tree [-r] owner/repo" in result.stderr
