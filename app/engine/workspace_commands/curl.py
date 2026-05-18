from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

import httpx

from app.core.settings import settings
from app.harness.commands import CommandSpec, first_flag, unsupported_flag
from app.harness.results import CommandResult
from app.harness.session import WorkspaceSession

ClientFactory = Callable[[], AbstractContextManager[httpx.Client]]


class CurlCommand:
    """Fetch URL content through Jina Reader using a curl-shaped command."""

    spec = CommandSpec(name="curl", forms=("curl URL",))

    def __init__(self, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or self._default_client

    def __call__(self, _session: WorkspaceSession, args: list[str]) -> CommandResult:
        if flag := first_flag(args):
            return unsupported_flag(self.spec, flag)
        if len(args) != 1:
            return CommandResult.error("curl: expected URL\n", exit_code=2)

        url = args[0]
        headers = {"User-Agent": "langgraph-researcher/1.0"}
        if settings.JINA_API_KEY:
            headers["Authorization"] = f"Bearer {settings.JINA_API_KEY}"

        try:
            with self._client_factory() as client:
                response = client.get(f"https://r.jina.ai/{url}", headers=headers)
                response.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            return CommandResult.error(
                f"curl: error fetching {url} via Jina: {exc}\n",
            )
        return CommandResult.ok(response.text)

    @staticmethod
    def _default_client() -> httpx.Client:
        return httpx.Client(timeout=15.0)
