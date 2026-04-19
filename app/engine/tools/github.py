"""GitHub helpers: plain functions and context-backed client/repo for tools."""

from langchain.tools import ToolRuntime, tool

from app.engine.schema import ResearchState
from app.services.gh_client.repo import GitHubRepositoryService


@tool("get_repo_tree", parse_docstring=True)
def get_repo_tree(
    repo_name: str,
    runtime: ToolRuntime[ResearchState],
) -> list[str] | None:
    """Fetch the default-branch file tree for a GitHub repository.

    Input should be in the format 'owner/repo' (for example,
    'octocat/Hello-World'). Returns a list of file paths in the repository
    or `None` if access fails or GitHub is not configured.
    """
    if runtime.state["gh_client"] is None:
        return None

    service = GitHubRepositoryService(
        runtime.state["gh_client"],
        repo_name=repo_name,
    )
    tree = service.get_tree()
    if tree is None:
        return None

    return [entry.path for entry in tree]
