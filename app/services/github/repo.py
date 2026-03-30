"""GitHub client with app installation auth.
Connection persists across workflow executions."""

from typing import TYPE_CHECKING

from github import Auth, Github
from github.GithubException import GithubException

from app.core.logger import logger

if TYPE_CHECKING:
    from github.Repository import Repository

    from app.core.settings import GithubConfig

_cached_github: Github | None = None
_cached_config_key: tuple[str, int, int, bool] | None = None


def _config_cache_key(cfg: "GithubConfig") -> tuple[str, int, int, bool]:
    """Stable, non-secret key used to invalidate stale client cache."""
    token_present = bool(cfg.token.get_secret_value())
    private_key_value = cfg.private_key.get_secret_value()
    private_key_hash = hash(private_key_value) if private_key_value else 0

    return (
        str(cfg.app_id),
        int(cfg.installation_id),
        private_key_hash,
        token_present,
    )


def get_github_client() -> Github | None:
    """
    Return a PyGithub client authenticated as the app installation.
    Uses a single cached instance per process so the connection
    persists across workflow runs.
    Returns None if GitHub is not configured (no app credentials or token).
    """
    global _cached_github, _cached_config_key

    from app.core.settings import settings

    cfg = settings.github
    if cfg is None:
        logger.debug("GitHub config missing; client unavailable")
        return None

    config_key = _config_cache_key(cfg)
    if _cached_github is not None and _cached_config_key == config_key:
        return _cached_github

    _cached_github = None
    _cached_config_key = None

    token = cfg.token.get_secret_value()
    if token:
        _cached_github = Github(auth=Auth.Token(token))
        _cached_config_key = config_key
        logger.debug("Initialized GitHub client using token auth")
        return _cached_github

    if cfg.app_id and cfg.private_key.get_secret_value() and cfg.installation_id:
        app_auth = Auth.AppAuth(cfg.app_id, cfg.private_key.get_secret_value())
        installation_auth = Auth.AppInstallationAuth(app_auth, cfg.installation_id)
        _cached_github = Github(auth=installation_auth)
        _cached_config_key = config_key
        logger.debug("Initialized GitHub client using app installation auth")
        return _cached_github

    logger.warning("GitHub client not initialized: incomplete auth configuration")
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
    global _cached_github, _cached_config_key
    _cached_github = None
    _cached_config_key = None
