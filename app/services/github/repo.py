"""GitHub client with app installation auth.
Connection persists across workflow executions."""

from typing import TYPE_CHECKING

from github import Auth, Github

if TYPE_CHECKING:
    from github.Repository import Repository

_cached_github: Github | None = None


def get_github_client() -> Github | None:
    """
    Return a PyGithub client authenticated as the app installation.
    Uses a single cached instance per process so the connection
    persists across workflow runs.
    Returns None if GitHub is not configured (no app credentials or token).
    """
    global _cached_github
    if _cached_github is not None:
        return _cached_github

    from app.core.settings import settings

    cfg = settings.github
    if cfg is None:
        return None

    token = cfg.token.get_secret_value()
    if token:
        _cached_github = Github(auth=Auth.Token(token))
        return _cached_github

    if cfg.app_id and cfg.private_key.get_secret_value() and cfg.installation_id:
        app_auth = Auth.AppAuth(cfg.app_id, cfg.private_key.get_secret_value())
        installation_auth = Auth.AppInstallationAuth(app_auth, cfg.installation_id)
        _cached_github = Github(auth=installation_auth)
        return _cached_github

    return None


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
    except Exception:
        return None


def clear_github_client() -> None:
    """Clear the cached client (e.g. for tests or config change)."""
    global _cached_github
    _cached_github = None
