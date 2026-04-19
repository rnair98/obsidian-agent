from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.core.paths import DEFAULT_ASSETS_DIR
from app.services.gh_client.repo import GITHUB_ARCHIVE_FORMAT, GitHubRepositoryService


class _FakeCommit:
    def __init__(self, sha: str) -> None:
        self.sha = sha


class _FakeRepo:
    def __init__(self) -> None:
        self.full_name = "owner/repo"
        self.default_branch = "main"
        self._sha = "sha-1"
        self.get_git_tree_calls = 0

    def get_commit(self, ref: str) -> _FakeCommit:
        assert ref == self.default_branch
        return _FakeCommit(self._sha)

    def get_git_tree(self, sha: str, recursive: bool = False) -> SimpleNamespace:
        assert recursive is True
        assert sha == self._sha
        self.get_git_tree_calls += 1
        return SimpleNamespace(tree=[sha])

    def get_archive_link(self, archive_format: str, ref: str) -> str:
        assert archive_format == GITHUB_ARCHIVE_FORMAT
        return f"https://example.invalid/{ref}.tar.gz"


class _FakeClient:
    def __init__(self, repo: _FakeRepo) -> None:
        self.repo = repo

    def get_repo(self, full_name_or_id: str, lazy: bool = False) -> _FakeRepo:
        assert full_name_or_id == self.repo.full_name
        assert lazy is True
        return self.repo


class _FakeFilesystemBackend:
    def __init__(self, existing_dirs: set[str] | None = None) -> None:
        self.base_path = DEFAULT_ASSETS_DIR
        self._existing_dirs = existing_dirs or set()

    def resolve(self, path: str | Path) -> Path:
        return (self.base_path / Path(path)).resolve()

    def is_dir(self, path: str | Path) -> bool:
        return str(path) in self._existing_dirs

    def list_dir(self, path: str | Path) -> list[Path]:
        if str(path) in self._existing_dirs:
            return [Path("already-present")]
        return []

    def mkdir(
        self,
        path: str | Path,
        parents: bool = True,
        exist_ok: bool = True,
    ) -> Path:
        self._existing_dirs.add(str(path))
        return self.resolve(path)

    def extract_tar_bytes(
        self,
        archive_bytes: bytes,
        destination: str | Path,
        strip_components: int = 1,
    ) -> Path:
        self._existing_dirs.add(str(destination))
        return self.resolve(destination)


def test_get_tree_caches_by_commit_sha() -> None:
    repo = _FakeRepo()
    service = GitHubRepositoryService(_FakeClient(repo), repo_name=repo.full_name)

    first_tree = service.get_tree()
    second_tree = service.get_tree()

    assert first_tree == ["sha-1"]
    assert second_tree == ["sha-1"]
    assert repo.get_git_tree_calls == 1


def test_get_tree_refreshes_when_commit_sha_changes() -> None:
    repo = _FakeRepo()
    service = GitHubRepositoryService(_FakeClient(repo), repo_name=repo.full_name)

    first_tree = service.get_tree()
    repo._sha = "sha-2"
    second_tree = service.get_tree()

    assert first_tree == ["sha-1"]
    assert second_tree == ["sha-2"]
    assert repo.get_git_tree_calls == 2


def test_shallow_clone_skips_when_snapshot_directory_is_non_empty() -> None:
    repo = _FakeRepo()
    snapshot_dir = f"owner/repo@{repo._sha}"
    backend = _FakeFilesystemBackend(existing_dirs={snapshot_dir})
    service = GitHubRepositoryService(
        _FakeClient(repo),
        repo_name=repo.full_name,
        filesystem_backend=backend,
    )

    result = service.shallow_clone()

    assert result is not None
    assert result["skipped"] is True
    assert result["commit_sha"] == repo._sha
