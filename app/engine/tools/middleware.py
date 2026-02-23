from langchain.agents.middleware import ContextEditingMiddleware, ToolRetryMiddleware
from requests import RequestException, Timeout

tool_retry = ToolRetryMiddleware(
    max_retries=1,
    retry_on=(RequestException, Timeout),
    backoff_factor=0.0,
)

context_editing = ContextEditingMiddleware()
