import httpx
from langchain_core.tools import tool

from app.settings import settings


@tool
def fetch_url(url: str) -> str:
    """
    Fetch the content of a specific URL using Jina Reader API
    and convert it to Markdown. Returns the markdown content or an error message.
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
