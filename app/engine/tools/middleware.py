from langchain.agents.middleware import ContextEditingMiddleware, ToolRetryMiddleware
from requests import RequestException, Timeout

tool_retry = ToolRetryMiddleware(
    max_retries=2,
    retry_on=(RequestException, Timeout),
    backoff_factor=1.5,
)

context_editing = ContextEditingMiddleware()
