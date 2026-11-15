from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from pathlib import Path

from app.engine.backends import assets_backend
from app.harness.commands import CommandSpec
from app.harness.results import CommandResult
from app.harness.session import WorkspaceSession
from app.services.gh_client.auth import get_github_handle
from app.services.gh_client.mirror import (
    READ_SUBCOMMANDS,
    MirrorError,
    ensure_mirror,
    run_git,
)
from app.services.gh_client.repo import GitHubRepositoryService

MAX_STDOUT_BYTES = 64 * 1024
TIMEOUT_SECONDS = 120.0
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+")
_MIRROR = re.compile(r"/repos/([A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+)\.git/?")
_WRITE_OR_EXEC_OPTIONS = ("output", "open-files-in-pager", "no-index")


def _default_service_factory(repo_name: str) -> GitHubRepositoryService:
    handle = get_github_handle()
    if handle is None:
        raise RuntimeError("GitHub is not configured")
    return GitHubRepositoryService(handle.client, repo_name=repo_name)


def _default_token() -> str | None:
    handle = get_github_handle()
    return handle.installation_token() if handle is not None else None


class GitCommand:
    """GitHub snapshots over REST; history reads on a Seatbelt-confined mirror."""

    spec = CommandSpec(
        name="git",
        forms=(
            "git ls-tree [-r] owner/repo",
            "git clone owner/repo [ref]",
            "git clone --bare owner/repo",
            "git -C /repos/owner/repo.git <"
            + "|".join(sorted(READ_SUBCOMMANDS))
            + "> [args]",
        ),
    )

    def __init__(
        self,
        service_factory: Callable[
            [str], GitHubRepositoryService
        ] = _default_service_factory,
        mirror_root: Path | None = None,
        token: Callable[[], str | None] = _default_token,
    ) -> None:
        self._service_factory = service_factory
        self._mirror_root = mirror_root
        self._token = token

    def __call__(self, session: WorkspaceSession, args: list[str]) -> CommandResult:
        _ = session
        try:
            match args:
                case ["-C", path, subcommand, *rest]:
                    return self._history(path, subcommand, rest)
                case ["ls-tree", *rest]:
                    return self._ls_tree(rest)
                case ["clone", "--bare", repo_name]:
                    return self._mirror(repo_name)
                case ["clone", *rest]:
                    return self._clone(rest)
                case _:
                    return self._usage("git: unsupported form")
        except MirrorError as exc:
            return CommandResult.error(f"git: {exc}\n")
        except subprocess.TimeoutExpired:
            return CommandResult.error(
                f"git: timed out after {TIMEOUT_SECONDS:.0f}s; "
                "narrow the revision range, -n, or -- <path>\n"
            )
        except Exception as exc:  # noqa: BLE001 - command boundary
            return CommandResult.error(f"git: {exc}\n", exit_code=1)

    def _history(self, path: str, subcommand: str, args: list[str]) -> CommandResult:
        match = _MIRROR.fullmatch(path)
        if match is None:
            return self._usage(f"git -C: expected /repos/owner/repo.git, got {path}")
        if subcommand not in READ_SUBCOMMANDS:
            return self._usage(f"git: unsupported subcommand: {subcommand}")
        if bad := next((arg for arg in args if _writes_or_execs(arg)), None):
            return self._usage(f"git {subcommand}: unsupported option: {bad}")
        mirror = self._mirror_path(match.group(1))
        if not mirror.is_dir():
            return CommandResult.error(
                f"git: no mirror at {path}; run: git clone --bare {match.group(1)}\n"
            )
        proc = run_git(
            mirror, [subcommand, *args], self._token(), timeout=TIMEOUT_SECONDS
        )
        return _bounded(proc, f"git {subcommand}", path)

    def _mirror(self, repo_name: str) -> CommandResult:
        if _REPO.fullmatch(repo_name) is None or ".." in repo_name:
            return self._usage(
                f"git clone --bare: expected owner/repo, got {repo_name}"
            )
        mirror = self._mirror_path(repo_name)
        action = "fetched" if mirror.exists() else "cloned"
        url = f"https://github.com/{repo_name}.git"
        proc = ensure_mirror(mirror, url, self._token(), timeout=TIMEOUT_SECONDS)
        if proc.returncode != 0:
            return CommandResult.error(
                f"git clone --bare: {proc.stderr.decode(errors='replace')}",
                exit_code=proc.returncode,
            )
        return CommandResult.ok(
            f"{action} {repo_name} to /repos/{repo_name}.git\n"
            f"next: git -C /repos/{repo_name}.git log --oneline -n 20 [-- <path>]\n"
        )

    def _mirror_path(self, repo_name: str) -> Path:
        root = self._mirror_root or assets_backend().resolve(".")
        return root / f"{repo_name}.git"

    def _ls_tree(self, args: list[str]) -> CommandResult:
        recursive = "-r" in args
        names = [arg for arg in args if arg != "-r"]
        if len(names) != 1 or names[0].startswith("-"):
            return self._usage("git ls-tree: expected [-r] owner/repo")
        tree = self._service_factory(names[0]).get_tree()
        if tree is None:
            return CommandResult.error(f"git ls-tree: cannot read {names[0]}\n")
        paths = [entry.path for entry in tree]
        if not recursive:
            paths = sorted({path.split("/", maxsplit=1)[0] for path in paths})
        return CommandResult.ok("".join(f"{path}\n" for path in sorted(paths)))

    def _clone(self, args: list[str]) -> CommandResult:
        if len(args) not in {1, 2} or args[0].startswith("-"):
            return self._usage("git clone: expected owner/repo [ref]")
        repo_name = args[0]
        ref = args[1] if len(args) == 2 else None
        snapshot = self._service_factory(repo_name).shallow_clone(ref)
        if snapshot is None:
            return CommandResult.error(f"git clone: cannot clone {repo_name}\n")
        virtual_path = f"/repos/{snapshot.repo_name}@{snapshot.commit_sha}"
        status = "cached" if snapshot.skipped else "cloned"
        return CommandResult.ok(
            f"{status} {snapshot.repo_name} {snapshot.requested_ref} "
            f"{snapshot.commit_sha} to {virtual_path}\n"
        )

    def _usage(self, message: str) -> CommandResult:
        forms = "\n  ".join(self.spec.forms)
        return CommandResult.error(
            f"{message}\nsupported forms:\n  {forms}\n", exit_code=2
        )


def _writes_or_execs(arg: str) -> bool:
    """Second layer only; Seatbelt is the boundary (ARCHITECTURE.md §10)."""
    if arg.startswith("-O"):
        return True
    name = arg.removeprefix("--").partition("=")[0]
    return (
        arg.startswith("--")
        and len(name) >= 2
        and any(option.startswith(name) for option in _WRITE_OR_EXEC_OPTIONS)
    )


def _bounded(
    proc: subprocess.CompletedProcess[bytes], label: str, scope: str
) -> CommandResult:
    stdout = proc.stdout[:MAX_STDOUT_BYTES].decode(errors="replace")
    notes = proc.stderr.decode(errors="replace")
    if len(proc.stdout) > MAX_STDOUT_BYTES:
        notes += (
            f"{label}: output truncated at {MAX_STDOUT_BYTES} of "
            f"{len(proc.stdout)} bytes; narrow with -n, --skip=N, or -- <path>\n"
        )
    elif proc.returncode == 0 and not proc.stdout:
        notes += f"{label}: no output for {scope}\n"
    return CommandResult(stdout=stdout, stderr=notes, exit_code=proc.returncode)
