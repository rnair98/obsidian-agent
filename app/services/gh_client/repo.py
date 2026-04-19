"""GitHub repository operations with app-installation auth."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from github import GithubException

from app.core.logger import logger
from app.core.paths import DEFAULT_ASSETS_DIR
from app.engine.backends import get_filesystem_backend
from app.services.gh_client.types import SnapshotResult

GITHUB_ARCHIVE_FORMAT = "tarball"

if TYPE_CHECKING:
    from github import Github
    from github.Repository import Repository

    from app.engine.backends import FilesystemBackend


class GitHubRepositoryService:
    """Operations for GitHub repositories using an injected PyGithub client."""

    def __init__(
        self,
        client: "Github",
        base_path: Path | None = None,
        repo_name: str | None = None,
        filesystem_backend: "FilesystemBackend | None" = None,
    ) -> None:
        self.client = client
        self.filesystem_backend = filesystem_backend or get_filesystem_backend(
            base_path=base_path or DEFAULT_ASSETS_DIR
        )
        self.repo = self._get_repo(repo_name)
        # Per-instance tree cache keyed by commit sha; avoids the
        # lru_cache-on-method pattern that would pin ``self`` forever.
        self._tree_cache: dict[str, Any] = {}

    def _get_repo(self, repo_name: str | None) -> "Repository | None":
        """Return a repository handle for `<owner>/<repo>` or None on access errors."""
        if not repo_name:
            return None

        try:
            return self.client.get_repo(full_name_or_id=repo_name, lazy=True)
        except GithubException as exc:
            logger.warning("GitHub repo access failed for '%s': %s", repo_name, exc)
            return None
        except Exception as exc:
            logger.exception(
                "Unexpected error fetching GitHub repo %s: %s",
                repo_name,
                exc,
            )
            return None

    def get_tree(self):
        """Get the repository tree for the default branch."""
        if self.repo is None:
            return None

        try:
            default_branch = self.repo.default_branch
            commit = self.repo.get_commit(default_branch)
            return self._get_tree_for_commit_sha(commit.sha)
        except GithubException as exc:
            logger.warning(
                "GitHub repo tree access failed for '%s': %s", self.repo.full_name, exc
            )
            return None
        except Exception as exc:
            logger.exception(
                "Unexpected error fetching GitHub repo tree for '%s': %s",
                self.repo.full_name,
                exc,
            )
            return None

    def _get_tree_for_commit_sha(self, commit_sha: str) -> Any:
        cached = self._tree_cache.get(commit_sha)
        if cached is not None:
            return cached
        tree = self.repo.get_git_tree(commit_sha, recursive=True).tree
        self._tree_cache[commit_sha] = tree
        return tree

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
                "Unable to resolve ref '%s' for '%s': %s",
                requested_ref,
                self.repo.full_name,
                exc,
            )
            return None
        except Exception as exc:
            logger.exception(
                "Unexpected error resolving ref '%s' for '%s': %s",
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

            return SnapshotResult(
                repo_name=self.repo.full_name,
                commit_sha=commit_sha,
                requested_ref=requested_ref,
                path=snapshot_dir,
                created_at=datetime.now(timezone.utc),
                skipped=False,
            )
        except Exception as exc:
            logger.exception(
                "Failed to snapshot '%s' at '%s' from tarball: %s",
                self.repo.full_name,
                commit_sha,
                exc,
            )
            # Best-effort cleanup of the empty dir we created above.
            try:
                self.filesystem_backend.delete_dir(
                    snapshot_relative_dir, missing_ok=True
                )
            except Exception:
                logger.debug(
                    "Failed to clean up partial snapshot at '%s'",
                    snapshot_relative_dir,
                )
            return None

    def _installation_token(self) -> str | None:
        try:
            token = self.client._Github__requester.auth.token
            token = token() if callable(token) else token
            return token if isinstance(token, str) and token else None
        except AttributeError:
            return None
