"""GitHub helpers: agent-facing tools wrapping :mod:`app.services.gh_client`."""

import asyncio

from langchain.tools import tool

from app.services.gh_client.auth import get_github_handle
from app.services.gh_client.repo import GitHubRepositoryService


def _fetch_tree_sync(repo_name: str) -> list[str] | None:
    handle = get_github_handle()
    if handle is None:
        return None
    service = GitHubRepositoryService(handle, repo_name=repo_name)
    tree = service.get_tree()
    if tree is None:
        return None
    return [entry.path for entry in tree]


@tool("get_repo_tree", parse_docstring=True)
async def get_repo_tree(repo_name: str) -> list[str] | None:
    """Fetch the default-branch file tree for a GitHub repository.

    Args:
        repo_name: Repository identifier in ``owner/repo`` form, for
            example ``octocat/Hello-World``.

    Returns:
        A list of file paths in the repository, or ``None`` if access
        fails or GitHub is not configured.
    """
    # PyGithub is sync — run on a worker thread so the agent's event loop
    # is not blocked on REST calls during research.
    return await asyncio.to_thread(_fetch_tree_sync, repo_name)
