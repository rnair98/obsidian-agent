from urllib.error import URLError
from urllib.request import Request, urlopen

from langchain_core.tools import tool


@tool
def fetch_url(url: str) -> tuple[str | None, str | None]:
    """
    Fetch the content of a specific URL (GET request).
    Returns the text content and an optional error message.
    """
    timeout = 10.0
    request = Request(url, headers={"User-Agent": "langgraph-researcher/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read(2000).decode("utf-8", errors="replace")
        return content, None
    except (URLError, ValueError) as exc:
        return None, str(exc)
