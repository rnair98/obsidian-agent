"""GitHub client with app installation auth.
Connection persists across workflow executions."""

import functools

from github import Auth, Github

from app.core.logger import logger


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


def clear_github_client() -> None:
    _create_github_client.cache_clear()
