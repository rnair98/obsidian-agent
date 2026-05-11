from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.harness.commands import CommandSpec
from app.harness.results import CommandResult
from app.harness.session import WorkspaceSession
from app.services.gh_client.auth import get_github_handle
from app.services.gh_client.repo import GitHubRepositoryService

GitHubServiceFactory = Callable[[str], GitHubRepositoryService]
GIT_FORMS = "git ls-tree [-r] owner/repo; git clone owner/repo [ref]"


def _default_service_factory(repo_name: str) -> GitHubRepositoryService:
    handle = get_github_handle()
    if handle is None:
        raise RuntimeError("GitHub is not configured")
    return GitHubRepositoryService(handle, repo_name=repo_name)


class GitCommand:
    """Read-oriented git-shaped command over GitHub repository services."""

    spec = CommandSpec(
        name="git",
        forms=("git ls-tree [-r] owner/repo", "git clone owner/repo [ref]"),
    )

    def __init__(
        self,
        service_factory: Callable[[str], Any] = _default_service_factory,
    ) -> None:
        self._service_factory = service_factory

    def __call__(self, session: WorkspaceSession, args: list[str]) -> CommandResult:
        _ = session
        if not args:
            return CommandResult.error("git: expected command\n", exit_code=2)
        command, *command_args = args
        try:
            match command:
                case "ls-tree":
                    return self._ls_tree(command_args)
                case "clone":
                    return self._clone(command_args)
                case _:
                    return CommandResult.error(
                        f"git: unsupported command: {command}; "
                        f"supported forms: {GIT_FORMS}\n",
                        exit_code=2,
                    )
        except RuntimeError as exc:
            return CommandResult.error(f"git: {exc}\n", exit_code=1)

    def _ls_tree(self, args: list[str]) -> CommandResult:
        recursive = False
        filtered_args: list[str] = []
        for arg in args:
            if arg == "-r":
                recursive = True
                continue
            if arg.startswith("-"):
                return CommandResult.error(
                    f"git ls-tree: unsupported flag: {arg}; "
                    "supported form: git ls-tree [-r] owner/repo\n",
                    exit_code=2,
                )
            filtered_args.append(arg)
        if len(filtered_args) != 1:
            return CommandResult.error(
                "git ls-tree: expected [-r] owner/repo\n", exit_code=2
            )
        repo_name = filtered_args[0]
        service = self._service_factory(repo_name)
        tree = service.get_tree()
        if tree is None:
            return CommandResult.error(f"git ls-tree: cannot read {repo_name}\n")
        paths = [entry.path for entry in tree]
        if not recursive:
            paths = sorted({path.split("/", maxsplit=1)[0] for path in paths})
        return CommandResult.ok("".join(f"{path}\n" for path in sorted(paths)))

    def _clone(self, args: list[str]) -> CommandResult:
        if len(args) not in {1, 2}:
            return CommandResult.error(
                "git clone: expected owner/repo [ref]\n", exit_code=2
            )
        repo_name = args[0]
        ref = args[1] if len(args) == 2 else None
        service = self._service_factory(repo_name)
        snapshot = service.shallow_clone(ref)
        if snapshot is None:
            return CommandResult.error(f"git clone: cannot clone {repo_name}\n")
        virtual_path = f"/repos/{snapshot.path.as_posix()}"
        status = "cached" if snapshot.skipped else "cloned"
        return CommandResult.ok(
            f"{status} {snapshot.repo_name} {snapshot.requested_ref} "
            f"{snapshot.commit_sha} to {virtual_path}\n"
        )
