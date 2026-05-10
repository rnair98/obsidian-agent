from __future__ import annotations

import pytest

from app.harness.fs import InMemoryWorkspaceBackend
from app.harness.mounts import CompositeWorkspaceBackend
from app.harness.paths import PathEscapeError, normalize_path
from app.harness.policy import PermissionPolicy, PermissionRule
from app.harness.session import WorkspaceSession


def test_normalize_path_keeps_relative_paths_inside_cwd() -> None:
    assert (
        normalize_path("notes/today.md", cwd="/workspace")
        == "/workspace/notes/today.md"
    )


def test_normalize_path_rejects_escape_above_root() -> None:
    with pytest.raises(PathEscapeError):
        normalize_path("../../secret", cwd="/workspace")


def test_composite_backend_routes_by_longest_mount_prefix() -> None:
    workspace = InMemoryWorkspaceBackend()
    memory = InMemoryWorkspaceBackend()
    backend = CompositeWorkspaceBackend(
        {
            "/": workspace,
            "/memory": memory,
        }
    )

    backend.write_text("/memory/fact.md", "persistent fact")
    backend.write_text("/scratch.md", "scratch")

    assert memory.read_text("/fact.md") == "persistent fact"
    assert workspace.read_text("/scratch.md") == "scratch"


def test_policy_uses_first_matching_rule() -> None:
    policy = PermissionPolicy(
        [
            PermissionRule.deny("delete", "/vault/**"),
            PermissionRule.allow("delete", "/vault/trash/**"),
        ]
    )

    assert policy.allows("delete", "/vault/trash/a.md") is False


def test_shell_runs_basic_file_crud_commands() -> None:
    session = WorkspaceSession.default()

    assert session.run("pwd").stdout == "/workspace\n"
    assert session.run("mkdir notes").exit_code == 0
    assert session.run("write notes/a.md hello").exit_code == 0
    assert session.run("cat notes/a.md").stdout == "hello"
    assert session.run("ls notes").stdout == "a.md\n"


def test_shell_rejects_unsupported_shell_syntax() -> None:
    session = WorkspaceSession.default()

    result = session.run("cat notes/a.md | wc -l")

    assert result.exit_code == 2
    assert "unsupported shell syntax" in result.stderr


def test_shell_enforces_permission_policy() -> None:
    session = WorkspaceSession.default()
    assert session.run("write /vault/a.md no").exit_code == 1


def test_shell_cd_persists_between_commands() -> None:
    session = WorkspaceSession.default()

    assert session.run("mkdir notes").exit_code == 0
    assert session.run("cd notes").exit_code == 0
    assert session.run("pwd").stdout == "/workspace/notes\n"
    assert session.run("write a.md hello").exit_code == 0

    assert session.backend.read_text("/workspace/notes/a.md") == "hello"
