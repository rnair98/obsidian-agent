"""GitHub helpers: plain functions and context-backed client/repo for tools."""

from langchain.tools import tool

from app.services.gh_client.auth import get_github_client
from app.services.gh_client.repo import GitHubRepositoryService


@tool("get_repo_tree", parse_docstring=True)
def get_repo_tree(repo_name: str) -> list[str] | None:
    """Fetch the default-branch file tree for a GitHub repository.

    Args:
        repo_name: Repository identifier in ``owner/repo`` form, for
            example ``octocat/Hello-World``.

    Returns:
        A list of file paths in the repository, or ``None`` if access
        fails or GitHub is not configured.
    """
    client = get_github_client()
    if client is None:
        return None

    service = GitHubRepositoryService(client, repo_name=repo_name)
    tree = service.get_tree()
    if tree is None:
        return None

    return [entry.path for entry in tree]
