from __future__ import annotations

import asyncio

import httpx
from langchain.tools import tool
from langchain_core.tools import tool as core_tool

from app.core.settings import settings
from app.engine.sandbox import ExecutionResult, LocalSubprocessSandboxBackend
from app.services.gh_client.auth import get_github_handle
from app.services.gh_client.repo import GitHubRepositoryService

EXPERIMENT_ERROR_PREFIX = "Experiment error"
NO_OUTPUT_MESSAGE = "Experiment completed with no output."


@core_tool(parse_docstring=True)
async def fetch_url(url: str) -> str:
    """Fetch a URL via Jina Reader and return its Markdown rendering.

    Args:
        url: Absolute URL to fetch. Jina Reader will render the page and
            return a Markdown transcription.

    Returns:
        The Markdown content of the page, or an error string prefixed with
        ``Error fetching URL`` if the request failed.
    """
    jina_url = f"https://r.jina.ai/{url}"
    headers = {"User-Agent": "langgraph-researcher/1.0"}

    if settings.JINA_API_KEY:
        headers["Authorization"] = f"Bearer {settings.JINA_API_KEY}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(jina_url, headers=headers)
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        return f"Error fetching URL {url} via Jina: {exc}"


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
    return await asyncio.to_thread(_fetch_tree_sync, repo_name)


def format_execution_result(result: ExecutionResult) -> str:
    if result.stderr:
        return f"{EXPERIMENT_ERROR_PREFIX}: {result.stderr}"
    return result.stdout or NO_OUTPUT_MESSAGE


@core_tool(parse_docstring=True)
async def run_python_experiment(code: str) -> str:
    """Run a snippet of Python code in a sandboxed subprocess.

    Args:
        code: Python source to execute. Runs with a 10-second timeout.

    Returns:
        The captured stdout on success, a message prefixed with
        ``Experiment error:`` on failure, or a placeholder when stdout is
        empty.
    """
    backend = LocalSubprocessSandboxBackend()
    result = await asyncio.to_thread(backend.run_python, code, 10)
    return format_execution_result(result)
