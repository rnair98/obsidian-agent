from __future__ import annotations

import pytest

from app.harness.commands import CommandSpec
from app.harness.fs import InMemoryWorkspaceBackend
from app.harness.mounts import CompositeWorkspaceBackend
from app.harness.paths import PathEscapeError, normalize_path
from app.harness.policy import PermissionPolicy, PermissionRule
from app.harness.results import CommandResult
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
    session = WorkspaceSession.scratch()

    assert session.run("pwd").stdout == "/workspace\n"
    assert session.run("mkdir notes").exit_code == 0
    assert session.run("write notes/a.md hello").exit_code == 0
    assert session.run("cat notes/a.md").stdout == "hello"
    assert session.run("ls notes").stdout == "a.md\n"


def test_shell_write_accepts_double_dash_content_boundary() -> None:
    session = WorkspaceSession.scratch()

    result = session.run('write report.md -- "# Report\n\nBody with spaces"')

    assert result.exit_code == 0
    assert session.run("cat report.md").stdout == "# Report\n\nBody with spaces"


def test_shell_rejects_unsupported_shell_syntax() -> None:
    session = WorkspaceSession.scratch()

    result = session.run("cat notes/a.md | wc -l")

    assert result.exit_code == 2
    assert "unsupported shell syntax" in result.stderr
    assert "help" in result.stderr


def test_shell_help_lists_exact_supported_command_forms() -> None:
    session = WorkspaceSession.scratch()

    result = session.run("help")

    assert result.exit_code == 0
    assert "Supported command forms:" in result.stdout
    assert "ls [path]" in result.stdout
    assert "No other flags" in result.stdout


def test_shell_help_command_scopes_to_one_command() -> None:
    session = WorkspaceSession.scratch()

    result = session.run("help grep")

    assert result.exit_code == 0
    assert result.stdout == "grep pattern path\n"


def test_shell_rejects_oversmart_core_command_flags_with_help_hint() -> None:
    session = WorkspaceSession.scratch()

    result = session.run("ls -la")

    assert result.exit_code == 2
    assert result.stderr == "ls: unsupported flag: -la; supported form: ls [path]\n"


def test_shell_rejects_oversmart_grep_flags_with_help_hint() -> None:
    session = WorkspaceSession.scratch()

    result = session.run("grep -R fact /memory")

    assert result.exit_code == 2
    expected = "grep: unsupported flag: -R; supported form: grep pattern path\n"
    assert result.stderr == expected


def test_shell_enforces_permission_policy() -> None:
    session = WorkspaceSession.scratch()
    assert session.run("write /repos/a.md no").exit_code == 1


def test_shell_cd_persists_between_commands() -> None:
    session = WorkspaceSession.scratch()

    assert session.run("mkdir notes").exit_code == 0
    assert session.run("cd notes").exit_code == 0
    assert session.run("pwd").stdout == "/workspace/notes\n"
    assert session.run("write a.md hello").exit_code == 0

    assert session.backend.read_text("/workspace/notes/a.md") == "hello"


def test_workspace_session_with_mounts_hides_composite_construction() -> None:
    memory = InMemoryWorkspaceBackend()
    memory.write_text("/prior.md", "settled")

    session = WorkspaceSession.with_mounts(
        {
            "/workspace": InMemoryWorkspaceBackend(),
            "/memory": memory,
        }
    )

    assert session.run("ls /").stdout == "memory\nworkspace\n"
    assert session.run("cat /memory/prior.md").stdout == "settled"


def test_workspace_session_dispatches_registered_commands() -> None:
    class FakeGit:
        spec = CommandSpec(
            name="git",
            forms=("git ls-tree [-r] owner/repo",),
        )

        def __call__(
            self,
            session: WorkspaceSession,
            args: list[str],
        ) -> CommandResult:
            return CommandResult.ok(f"{session.cwd}: {' '.join(args)}\n")

    session = WorkspaceSession.with_mounts(
        {"/workspace": InMemoryWorkspaceBackend()},
        commands=[FakeGit()],
    )

    assert (
        session.run("git ls-tree -r owner/repo").stdout
        == "/workspace: ls-tree -r owner/repo\n"
    )


def test_shell_help_uses_registered_command_specs() -> None:
    class FakeCurl:
        spec = CommandSpec(name="curl", forms=("curl URL",))

        def __call__(
            self,
            session: WorkspaceSession,
            args: list[str],
        ) -> CommandResult:
            return CommandResult.ok()

    session = WorkspaceSession.with_mounts(
        {"/workspace": InMemoryWorkspaceBackend()},
        commands=[FakeCurl()],
    )

    assert session.run("help curl").stdout == "curl URL\n"
    assert "curl URL" in session.run("help").stdout
