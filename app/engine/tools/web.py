import httpx
from langchain_core.tools import tool

from app.core.settings import settings


@tool(parse_docstring=True)
def fetch_url(url: str) -> str:
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
        with httpx.Client(timeout=15.0) as client:
            response = client.get(jina_url, headers=headers)
            response.raise_for_status()
            return response.text
    except httpx.HTTPError as exc:
        return f"Error fetching URL {url} via Jina: {str(exc)}"
