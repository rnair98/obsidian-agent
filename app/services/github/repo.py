"""GitHub client with app installation auth.
Connection persists across workflow executions."""

from typing import TYPE_CHECKING

from github import Auth, Github
from github.GithubException import GithubException

from app.core.logger import logger

if TYPE_CHECKING:
    from github.Repository import Repository

import functools


@functools.lru_cache(maxsize=1)
def _create_github_client(
    app_id: str, installation_id: int, private_key_val: str
) -> Github | None:
    """Creates and caches the GitHub client based on auth params."""
    if app_id and private_key_val and installation_id:
        app_auth = Auth.AppAuth(int(app_id), private_key_val)
        installation_auth = Auth.AppInstallationAuth(app_auth, installation_id)
        logger.debug("Initialized GitHub client using app installation auth")
        return Github(auth=installation_auth)

    logger.warning("GitHub client not initialized: incomplete App auth configuration")
    return None


def get_github_client() -> Github | None:
    """
    Return a PyGithub client authenticated as the app installation.
    Uses a single cached instance per process so the connection
    persists across workflow runs. Auto-invalidates if settings change.
    Returns None if GitHub is not configured (no app credentials).
    """
    from app.core.settings import settings

    cfg = settings.github
    if cfg is None:
        logger.debug("GitHub config missing; client unavailable")
        return None

    return _create_github_client(
        str(cfg.app_id), cfg.installation_id, cfg.private_key.get_secret_value()
    )


def get_github_repo(repo_name: str) -> "Repository | None":
    """
    Return a PyGithub Repository for the given full name (owner/repo), or None if
    GitHub is not configured or the repo cannot be accessed.
    Uses the session-persistent app installation client.
    """
    client = get_github_client()
    if client is None:
        return None
    try:
        return client.get_repo(full_name_or_id=repo_name, lazy=True)
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


def clear_github_client() -> None:
    """Clear the cached client (e.g. for tests or config change)."""
    _create_github_client.cache_clear()
