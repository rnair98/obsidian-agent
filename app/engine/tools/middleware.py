from httpx import HTTPError, TimeoutException
from langchain.agents.middleware import ContextEditingMiddleware, ToolRetryMiddleware

tool_retry = ToolRetryMiddleware(
    max_retries=1,
    retry_on=(HTTPError, TimeoutException),
    backoff_factor=0.0,
)

context_editing = ContextEditingMiddleware()
