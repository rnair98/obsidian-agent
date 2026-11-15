from __future__ import annotations

import inspect
import io
import tarfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.services.gh_client.repo import GitHubRepositoryService


def _tarball(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"owner-repo-abc/{name}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class _FakeGitHub:
    """githubkit's client shape at the call sites the service uses."""

    def __init__(self, *, offline: bool = False) -> None:
        self.offline = offline
        self.head = "sha-1"
        self.requests: list[str] = []
        self.rest = SimpleNamespace(
            repos=SimpleNamespace(
                get=self._repo,
                get_commit=self._commit,
                download_tarball_archive=self._tarball,
            ),
            git=SimpleNamespace(get_tree=self._tree),
        )

    def _record(self, name: str) -> None:
        if self.offline:
            raise AssertionError(f"unexpected GitHub request: {name}")
        self.requests.append(name)

    def _repo(self, owner: str, repo: str) -> Any:
        self._record("repos.get")
        return SimpleNamespace(parsed_data=SimpleNamespace(default_branch="main"))

    def _commit(self, owner: str, repo: str, ref: str) -> Any:
        self._record("repos.get_commit")
        return SimpleNamespace(parsed_data=SimpleNamespace(sha=self.head))

    def _tree(self, owner: str, repo: str, tree_sha: str, *, recursive: str) -> Any:
        self._record("git.get_tree")
        assert recursive == "1"
        return SimpleNamespace(
            parsed_data=SimpleNamespace(tree=[SimpleNamespace(path=tree_sha)])
        )

    def _tarball(self, owner: str, repo: str, ref: str) -> Any:
        self._record("repos.download_tarball_archive")
        return SimpleNamespace(content=_tarball({"README.md": f"at {ref}\n"}))


def _service(client: _FakeGitHub, tmp_path: Path) -> GitHubRepositoryService:
    backend = InProcessFilesystemBackend(base_path=tmp_path)
    return GitHubRepositoryService(
        client,  # type: ignore[arg-type]
        repo_name="owner/repo",
        filesystem_backend=backend,
    )


def test_get_tree_fetches_each_commit_tree_once(tmp_path: Path) -> None:
    client = _FakeGitHub()
    service = _service(client, tmp_path)

    first = service.get_tree()
    again = service.get_tree()
    client.head = "sha-2"
    moved = service.get_tree()

    assert [entry.path for entry in first or []] == ["sha-1"]
    assert again == first
    assert [entry.path for entry in moved or []] == ["sha-2"]
    assert client.requests.count("git.get_tree") == 2


def test_shallow_clone_extracts_the_commit_and_then_reuses_it(tmp_path: Path) -> None:
    client = _FakeGitHub()
    service = _service(client, tmp_path)

    cloned = service.shallow_clone()
    cached = service.shallow_clone()

    assert cloned is not None and cloned.skipped is False
    assert (tmp_path / "owner" / "repo@sha-1" / "README.md").read_text() == "at sha-1\n"
    assert cached is not None and cached.skipped is True
    assert client.requests.count("repos.download_tarball_archive") == 1


def test_fake_matches_githubkit_call_signatures() -> None:
    from githubkit import GitHub

    client = GitHub("unused")
    real = client.rest
    fake = _FakeGitHub().rest
    for group, method in [
        ("repos", "get"),
        ("repos", "get_commit"),
        ("repos", "download_tarball_archive"),
        ("git", "get_tree"),
    ]:
        real_params = inspect.signature(
            getattr(getattr(real, group), method)
        ).parameters
        fake_params = inspect.signature(
            getattr(getattr(fake, group), method)
        ).parameters
        assert set(fake_params) <= set(real_params), (group, method)
