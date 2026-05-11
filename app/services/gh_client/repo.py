"""GitHub repository operations with app-installation auth."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from github import GithubException

from app.core.logger import logger
from app.engine.backends import assets_backend, get_filesystem_backend
from app.engine.backends.errors import FilesystemBackendError
from app.services.gh_client.auth import GitHubHandle
from app.services.gh_client.types import SnapshotResult

GITHUB_ARCHIVE_FORMAT = "tarball"

if TYPE_CHECKING:
    from github import Github
    from github.GitTreeElement import GitTreeElement
    from github.Repository import Repository

    from app.engine.backends import FilesystemBackend


class GitHubRepositoryService:
    """Operations for GitHub repositories using an injected PyGithub client."""

    def __init__(
        self,
        client: "Github | GitHubHandle",
        base_path: Path | None = None,
        repo_name: str | None = None,
        filesystem_backend: "FilesystemBackend | None" = None,
    ) -> None:
        if isinstance(client, GitHubHandle):
            self._handle: GitHubHandle | None = client
            self.client = client.client
        else:
            self._handle = None
            self.client = client
        if filesystem_backend is not None:
            self.filesystem_backend = filesystem_backend
        elif base_path is not None:
            self.filesystem_backend = get_filesystem_backend(base_path=base_path)
        else:
            self.filesystem_backend = assets_backend()

        self.repo_name = repo_name
        self.repo = self._get_repo(repo_name) if repo_name is not None else None
        self._tree_cache: dict[str, Any] = {}

    def _get_repo(self, repo_name: str) -> "Repository | None":
        """Return a repository handle for `<owner>/<repo>` or None on access errors."""
        try:
            return self.client.get_repo(full_name_or_id=repo_name, lazy=True)
        except GithubException as exc:
            logger.warning("GitHub repo access failed for '{}': {}", repo_name, exc)
            return None

    def get_tree(self) -> "list[GitTreeElement] | None":
        """Get the repository tree for the default branch."""
        if self.repo is None:
            return None

        try:
            default_branch = self.repo.default_branch
            commit = self.repo.get_commit(default_branch)
            return self._get_tree_for_commit_sha(commit.sha)
        except GithubException as exc:
            logger.warning(
                "GitHub repo tree access failed for '{}': {}",
                self.repo.full_name,
                exc,
            )
            return None

    def _get_tree_for_commit_sha(
        self, commit_sha: str
    ) -> "list[GitTreeElement] | None":
        cached = self._tree_cache.get(commit_sha)
        if cached is not None:
            return cached

        if self.repo is None:
            logger.warning(
                "Attempted to get tree for commit '{}' but repo is unavailable",
                commit_sha,
            )
            return None

        tree = self.repo.get_git_tree(commit_sha, recursive=True).tree
        self._tree_cache[commit_sha] = tree
        return tree

    def list_snapshots(self) -> list[SnapshotResult]:
        """List all snapshots for the repository."""
        if self.repo_name is None:
            return []

        # Prefer the canonical full name from the GitHub API so we read from
        # the same directory ``shallow_clone()`` writes to (it uses
        # ``self.repo.full_name``). Falling back to the raw constructor arg
        # only when the repo handle is unavailable keeps offline/list-only
        # callers working.
        canonical_name = (
            self.repo.full_name if self.repo is not None else self.repo_name
        )
        try:
            owner, repo_name = canonical_name.split("/", maxsplit=1)
        except ValueError:
            logger.warning(
                "Invalid GitHub repo name for snapshot listing: {}",
                canonical_name,
            )
            return []
        snapshot_root = Path(owner)
        snapshot_prefix = f"{repo_name}@"

        snapshots: list[SnapshotResult] = []
        for path in self.filesystem_backend.list_dir(snapshot_root):
            if not path.is_dir() or not path.name.startswith(snapshot_prefix):
                continue
            commit_sha = path.name[len(snapshot_prefix) :]
            snapshots.append(
                SnapshotResult(
                    repo_name=canonical_name,
                    commit_sha=commit_sha,
                    requested_ref=commit_sha,
                    path=path,
                    created_at=datetime.fromtimestamp(
                        path.stat().st_mtime,
                        tz=timezone.utc,
                    ),
                    skipped=False,
                )
            )
        return snapshots

    def delete_snapshot(self, snapshot: SnapshotResult) -> bool:
        """Delete a snapshot directory from the local filesystem backend."""
        if not self.filesystem_backend.exists(snapshot.path):
            return False
        try:
            self.filesystem_backend.delete_dir(snapshot.path, missing_ok=True)
            return True
        except OSError as exc:
            logger.warning(
                "Failed to delete snapshot '{}' for '{}': {}",
                snapshot.commit_sha,
                snapshot.repo_name,
                exc,
            )
            return False

    def shallow_clone(
        self,
        ref: str | None = None,
    ) -> SnapshotResult | None:
        """
        Snapshot a repository by downloading a tarball pinned to a resolved commit SHA.

        Inputs:
        - repo_name: `<owner>/<repo>`
        - ref: optional branch/tag/sha; defaults to default branch
        """

        if self.repo is None:
            return None

        requested_ref = ref or self.repo.default_branch
        try:
            commit_sha = self.repo.get_commit(requested_ref).sha
        except GithubException as exc:
            logger.warning(
                "Unable to resolve ref '{}' for '{}': {}",
                requested_ref,
                self.repo.full_name,
                exc,
            )
            return None

        owner, name = self.repo.full_name.split("/")
        snapshot_relative_dir = Path(owner) / f"{name}@{commit_sha}"
        snapshot_dir = self.filesystem_backend.resolve(snapshot_relative_dir)

        if self.filesystem_backend.is_dir(
            snapshot_relative_dir
        ) and self.filesystem_backend.list_dir(snapshot_relative_dir):
            return SnapshotResult(
                repo_name=self.repo.full_name,
                commit_sha=commit_sha,
                requested_ref=requested_ref,
                path=snapshot_dir,
                created_at=datetime.now(timezone.utc),
                skipped=True,
            )

        self.filesystem_backend.mkdir(snapshot_relative_dir)
        archive_url = self.repo.get_archive_link(GITHUB_ARCHIVE_FORMAT, commit_sha)

        headers: dict[str, str] = {}
        token = self._installation_token()
        if token:
            headers["Authorization"] = f"token {token}"

        try:
            with httpx.Client(timeout=90.0, follow_redirects=True) as client:
                response = client.get(archive_url, headers=headers)
                response.raise_for_status()
                self.filesystem_backend.extract_tar_bytes(
                    response.content,
                    destination=snapshot_relative_dir,
                    strip_components=1,
                )
        except (httpx.HTTPError, OSError, FilesystemBackendError) as exc:
            logger.warning(
                "Failed to snapshot '{}' at '{}' from tarball: {}",
                self.repo.full_name,
                commit_sha,
                exc,
            )
            # Best-effort cleanup of the empty dir we created above.
            try:
                self.filesystem_backend.delete_dir(
                    snapshot_relative_dir, missing_ok=True
                )
            except OSError:
                logger.debug(
                    "Failed to clean up partial snapshot at '{}'",
                    snapshot_relative_dir,
                )
            return None

        return SnapshotResult(
            repo_name=self.repo.full_name,
            commit_sha=commit_sha,
            requested_ref=requested_ref,
            path=snapshot_dir,
            created_at=datetime.now(timezone.utc),
            skipped=False,
        )

    def _installation_token(self) -> str | None:
        if self._handle is not None:
            return self._handle.installation_token
        return None
