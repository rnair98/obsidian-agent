"""GitHub client with app installation auth.
Connection persists across workflow executions."""

from __future__ import annotations

import functools
from dataclasses import dataclass

from github import Auth, Github

from app.core.logger import logger


@dataclass(frozen=True, slots=True)
class GitHubHandle:
    """Bundles a configured Github client with its installation auth.

    Holding the auth alongside the client avoids reaching into PyGithub's
    name-mangled internals when callers need the installation token (e.g.
    to authenticate raw httpx archive downloads).
    """

    client: Github
    auth: Auth.AppInstallationAuth

    @property
    def installation_token(self) -> str | None:
        token = self.auth.token
        return token if isinstance(token, str) and token else None


@functools.lru_cache(maxsize=1)
def _create_github_handle(
    app_id: int, installation_id: int, private_key_val: str
) -> GitHubHandle | None:
    """Create and cache the GitHub client + auth bundle."""
    if app_id and private_key_val and installation_id:
        app_auth = Auth.AppAuth(app_id, private_key_val)
        installation_auth = Auth.AppInstallationAuth(app_auth, installation_id)
        logger.debug("Initialized GitHub client using app installation auth")
        return GitHubHandle(
            client=Github(auth=installation_auth), auth=installation_auth
        )

    logger.warning("GitHub client not initialized: incomplete App auth configuration")
    return None


def get_github_handle() -> GitHubHandle | None:
    """Return the cached GitHub handle (client + auth) or None if unconfigured."""
    from app.core.settings import settings

    cfg = settings.github
    if cfg is None:
        logger.debug("GitHub config missing; client unavailable")
        return None

    return _create_github_handle(
        cfg.app_id, cfg.installation_id, cfg.private_key.get_secret_value()
    )


def get_github_client() -> Github | None:
    """Return the PyGithub client authenticated as the app installation."""
    handle = get_github_handle()
    return handle.client if handle is not None else None


def clear_github_client() -> None:
    _create_github_handle.cache_clear()
