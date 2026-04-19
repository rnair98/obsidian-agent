from typing import Any

import httpx
import orjson
from langchain_core.tools import tool

from app.core.settings import settings
from app.engine.schema import SearchQuery


def quote_term(term: str) -> str:
    return f'"{term}"' if " " in term else term


def clean_terms(terms: list[str]) -> list[str]:
    cleaned = [term.strip() for term in terms if term.strip()]
    seen: set[str] = set()
    deduped: list[str] = []
    for term in cleaned:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


def build_boolean_query(query: SearchQuery) -> str:
    if query["raw"]:
        return query["raw"]

    parts: list[str] = []
    any_terms = clean_terms(query["any_terms"])
    all_terms = clean_terms(query["all_terms"])
    phrases = clean_terms(query["phrases"])
    excluded = clean_terms(query["excluded"])
    sites = clean_terms(query["sites"])
    filetypes = clean_terms(query["filetypes"])
    intitle = clean_terms(query["intitle"])
    inurl = clean_terms(query["inurl"])

    if any_terms:
        if len(any_terms) == 1:
            parts.append(quote_term(any_terms[0]))
        else:
            parts.append(
                "(" + " OR ".join(quote_term(term) for term in any_terms) + ")"
            )
    for term in all_terms:
        parts.append(quote_term(term))
    for term in phrases:
        parts.append(f'"{term}"')
    for term in excluded:
        parts.append(f"NOT {quote_term(term)}")
    if sites:
        if len(sites) == 1:
            parts.append(f"site:{sites[0]}")
        else:
            site_parts = " OR ".join(f"site:{site}" for site in sites)
            parts.append(f"({site_parts})")
    for filetype in filetypes:
        parts.append(f"filetype:{filetype}")
    for title in intitle:
        parts.append(f"intitle:{quote_term(title)}")
    for url in inurl:
        parts.append(f"inurl:{quote_term(url)}")
    return " AND ".join(parts) if parts else ""


def build_semantic_query(query: SearchQuery, fallback: str) -> str:
    if query["raw"]:
        return query["raw"]
    all_terms = clean_terms(query["all_terms"])
    any_terms = clean_terms(query["any_terms"])
    phrases = clean_terms(query["phrases"])
    parts = phrases + all_terms + any_terms
    return " ".join(parts) if parts else fallback


@tool(parse_docstring=True)
def call_brave_search(query: str) -> tuple[list[dict[str, str]], str | None]:
    """Search the web using Brave Search.

    Args:
        query: Boolean or natural-language search expression to send to
            Brave. Capped to ``settings.DEFAULT_SEARCH_LIMIT`` results.

    Returns:
        A ``(results, error)`` pair. ``results`` is a list of dictionaries
        with ``title``, ``url``, ``notes``, ``provider``, and ``score``
        keys. ``error`` is ``None`` on success or a descriptive string if
        the API key is missing or the request failed.
    """
    limit = settings.DEFAULT_SEARCH_LIMIT
    api_key = settings.BRAVE_SEARCH_API_KEY
    if not api_key:
        return [], "BRAVE_SEARCH_API_KEY is not set."

    url = settings.BRAVE_SEARCH_URL
    params = {"q": query, "count": limit}
    headers = {
        "Accept": "application/json",
        "X-Subscription-Token": api_key,
        "User-Agent": "langgraph-researcher/1.0",
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return [], f"Brave search failed: {exc}"

    results = []
    for entry in payload.get("web", {}).get("results", []):
        results.append(
            {
                "title": entry.get("title", ""),
                "url": entry.get("url", ""),
                "notes": entry.get("description", ""),
                "provider": "brave",
                "score": str(entry.get("score", "")),
            }
        )
    return results, None


@tool(parse_docstring=True)
def call_exa_search(
    query: str, search_type: str = "auto"
) -> tuple[list[dict[str, str]], str | None]:
    """Search using Exa.ai's neural/semantic search.

    Args:
        query: Natural-language search expression. Exa's autoprompt is
            always enabled.
        search_type: Optional search mode, e.g. ``auto`` (default),
            ``neural``, or ``keyword``. ``auto`` lets Exa choose.

    Returns:
        A ``(results, error)`` pair. ``results`` is a list of dictionaries
        with ``title``, ``url``, ``notes``, ``provider``, and ``score``
        keys. ``error`` is ``None`` on success or a descriptive string if
        the API key is missing or the request failed.
    """
    limit = settings.DEFAULT_SEARCH_LIMIT
    api_key = settings.EXA_API_KEY
    if not api_key:
        return [], "EXA_API_KEY is not set."

    payload: dict[str, Any] = {
        "query": query,
        "numResults": limit,
        "useAutoprompt": True,
    }
    if search_type and search_type != "auto":
        payload["type"] = search_type

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "x-api-key": api_key,
        "User-Agent": "langgraph-researcher/1.0",
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                settings.EXA_SEARCH_URL,
                content=orjson.dumps(payload),
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return [], f"Exa search failed: {exc}"

    results = []
    for entry in data.get("results", []):
        results.append(
            {
                "title": entry.get("title", ""),
                "url": entry.get("url", ""),
                "notes": entry.get("snippet", ""),
                "provider": "exa",
                "score": str(entry.get("score", "")),
            }
        )
    return results, None


@tool(parse_docstring=True)
def call_exa_context(query: str) -> tuple[str | None, str | None]:
    """Fetch code context or snippets from Exa for a programming query.

    Useful for retrieving code examples or library documentation relevant
    to a task.

    Args:
        query: Natural-language description of the code context needed.

    Returns:
        A ``(response, error)`` pair. ``response`` is the Markdown context
        string on success or ``None`` otherwise. ``error`` is ``None`` on
        success or a descriptive string if the API key is missing or the
        request failed.
    """
    tokens_num = 1000  # Default
    api_key = settings.EXA_API_KEY
    if not api_key:
        return None, "EXA_API_KEY is not set."

    payload = {
        "query": query,
        "tokensNum": tokens_num,
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "User-Agent": "langgraph-researcher/1.0",
    }

    try:
        with httpx.Client(timeout=20.0) as client:
            response = client.post(
                settings.EXA_CONTEXT_URL,
                content=orjson.dumps(payload),
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response"), None
    except (httpx.HTTPError, ValueError) as exc:
        return None, f"Exa context search failed: {exc}"


def merge_sources(
    primary: list[dict[str, str]],
    secondary: list[dict[str, str]],
    limit: int,
) -> list[dict[str, str]]:
    seen: dict[str, float] = {}
    merged: list[dict[str, str]] = []
    for index, entry in enumerate(primary + secondary):
        url = entry.get("url", "")
        if not url:
            continue
        raw_score = entry.get("score", "")
        try:
            score = float(raw_score) if raw_score else 0.0
        except ValueError:
            score = 0.0
        if entry.get("title"):
            score += 0.5
        if entry.get("notes"):
            score += 0.5
        score += 1.0 / (index + 1)
        if url not in seen or score > seen[url]:
            seen[url] = score
            merged.append(entry)
    merged.sort(key=lambda item: seen.get(item.get("url", ""), 0.0), reverse=True)
    return merged[:limit]
