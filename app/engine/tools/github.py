"""GitHub helpers: plain functions and context-backed client/repo for tools."""

from typing import TYPE_CHECKING

from app.services.github.repo import get_github_client, get_github_repo

if TYPE_CHECKING:
    from github import Github
    from github.Repository import Repository


def resolve_github_client() -> "Github | None":
    """Return shared GitHub client for engine/tool callers."""
    return get_github_client()


def resolve_github_repo(repo_name: str) -> "Repository | None":
    """Return repository handle for `<owner>/<repo>` name."""
    return get_github_repo(repo_name)
