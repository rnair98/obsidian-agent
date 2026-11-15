"""GitHub App installation auth. Connection persists across workflow executions."""

from __future__ import annotations

import functools
from datetime import datetime, timedelta, timezone

from githubkit import AppAuthStrategy, AppInstallationAuthStrategy, GitHub

from app.core.logger import logger

_TOKEN_MARGIN = timedelta(minutes=5)
_TIMEOUT_SECONDS = 90.0


class GitHubHandle:
    """Installation-authenticated REST client plus a raw token for the git CLI."""

    def __init__(self, app_id: int, private_key: str, installation_id: int) -> None:
        self.client = GitHub(
            AppInstallationAuthStrategy(app_id, private_key, installation_id),
            timeout=_TIMEOUT_SECONDS,
        )
        self._app = GitHub(
            AppAuthStrategy(app_id, private_key), timeout=_TIMEOUT_SECONDS
        )
        self._installation_id = installation_id
        self._token: tuple[str, datetime] | None = None

    def installation_token(self) -> str:
        now = datetime.now(timezone.utc)
        if self._token is None or self._token[1] - _TOKEN_MARGIN <= now:
            minted = self._app.rest.apps.create_installation_access_token(
                self._installation_id
            ).parsed_data
            self._token = (minted.token, minted.expires_at)
        return self._token[0]


@functools.lru_cache(maxsize=1)
def _create_github_handle(
    app_id: int, installation_id: int, private_key_val: str
) -> GitHubHandle | None:
    if app_id and private_key_val and installation_id:
        logger.debug("Initialized GitHub client using app installation auth")
        return GitHubHandle(app_id, private_key_val, installation_id)

    logger.warning("GitHub client not initialized: incomplete App auth configuration")
    return None


def get_github_handle() -> GitHubHandle | None:
    """Return the cached GitHub handle or None if unconfigured."""
    from app.core.settings import settings

    cfg = settings.github
    if cfg is None:
        logger.debug("GitHub config missing; client unavailable")
        return None

    return _create_github_handle(
        cfg.app_id, cfg.installation_id, cfg.private_key.get_secret_value()
    )
