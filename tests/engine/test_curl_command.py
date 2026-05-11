from __future__ import annotations

import httpx

from app.engine.workspace_commands.curl import CurlCommand
from app.harness.session import WorkspaceSession


def test_curl_command_fetches_markdown_via_jina() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["user_agent"] = request.headers["User-Agent"]
        return httpx.Response(200, text="# Page")

    command = CurlCommand(
        client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=15.0,
        )
    )

    result = command(WorkspaceSession.scratch(), ["https://example.com/page"])

    assert result.exit_code == 0
    assert result.stdout == "# Page"
    assert seen == {
        "url": "https://r.jina.ai/https://example.com/page",
        "user_agent": "langgraph-researcher/1.0",
    }


def test_curl_command_rejects_flags_with_supported_form() -> None:
    command = CurlCommand()

    result = command(WorkspaceSession.scratch(), ["-L", "https://example.com"])

    assert result.exit_code == 2
    assert result.stderr == ("curl: unsupported flag: -L; supported form: curl URL\n")


def test_curl_command_reports_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable", request=request)

    command = CurlCommand(
        client_factory=lambda: httpx.Client(
            transport=httpx.MockTransport(handler),
            timeout=15.0,
        )
    )

    result = command(WorkspaceSession.scratch(), ["https://example.com"])

    assert result.exit_code == 1
    assert "curl: error fetching https://example.com via Jina:" in result.stderr
