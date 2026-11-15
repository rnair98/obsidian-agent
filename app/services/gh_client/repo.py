"""GitHub repository operations over an installation-authenticated client."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from githubkit.exception import GitHubException

from app.core.logger import logger
from app.engine.backends import assets_backend
from app.engine.backends.errors import FilesystemBackendError
from app.services.gh_client.types import SnapshotResult

if TYPE_CHECKING:
    from githubkit import GitHub
    from githubkit.versions.latest.models import GitTreePropTreeItems

    from app.engine.backends import FilesystemBackend


class GitHubRepositoryService:
    """Read one `<owner>/<repo>` through the REST API. Construction is offline."""

    def __init__(
        self,
        client: "GitHub",
        repo_name: str,
        filesystem_backend: "FilesystemBackend | None" = None,
    ) -> None:
        self.client = client
        self.repo_name = repo_name
        self.owner, _, self.name = repo_name.partition("/")
        self.filesystem_backend = filesystem_backend or assets_backend()
        self._tree_cache: dict[str, list[GitTreePropTreeItems]] = {}

    def get_tree(self) -> "list[GitTreePropTreeItems] | None":
        """Get the recursive tree of the default branch."""
        try:
            sha = self._commit_sha(self._default_branch())
            if sha not in self._tree_cache:
                self._tree_cache[sha] = self.client.rest.git.get_tree(
                    self.owner, self.name, sha, recursive="1"
                ).parsed_data.tree
        except GitHubException as exc:
            logger.warning(
                "GitHub tree access failed for '{}': {}", self.repo_name, exc
            )
            return None
        return self._tree_cache[sha]

    def shallow_clone(self, ref: str | None = None) -> SnapshotResult | None:
        """Extract the tarball at `ref` (default branch) to `{owner}/{repo}@{sha}`."""
        try:
            requested_ref = ref or self._default_branch()
            commit_sha = self._commit_sha(requested_ref)
        except GitHubException as exc:
            logger.warning(
                "Unable to resolve ref '{}' for '{}': {}", ref, self.repo_name, exc
            )
            return None

        relative_dir = Path(self.owner) / f"{self.name}@{commit_sha}"
        result = SnapshotResult(
            repo_name=self.repo_name,
            commit_sha=commit_sha,
            requested_ref=requested_ref,
            path=self.filesystem_backend.resolve(relative_dir),
            created_at=datetime.now(timezone.utc),
            skipped=True,
        )
        if self.filesystem_backend.is_dir(
            relative_dir
        ) and self.filesystem_backend.list_dir(relative_dir):
            return result

        self.filesystem_backend.mkdir(relative_dir)
        try:
            archive = self.client.rest.repos.download_tarball_archive(
                self.owner, self.name, commit_sha
            ).content
            self.filesystem_backend.extract_tar_bytes(
                archive, destination=relative_dir, strip_components=1
            )
        except (GitHubException, OSError, FilesystemBackendError) as exc:
            logger.warning(
                "Failed to snapshot '{}' at '{}': {}", self.repo_name, commit_sha, exc
            )
            self.filesystem_backend.delete_dir(relative_dir, missing_ok=True)
            return None
        return result.model_copy(update={"skipped": False})

    def _default_branch(self) -> str:
        return self.client.rest.repos.get(
            self.owner, self.name
        ).parsed_data.default_branch

    def _commit_sha(self, ref: str) -> str:
        return self.client.rest.repos.get_commit(
            self.owner, self.name, ref
        ).parsed_data.sha
