from httpx import HTTPError, TimeoutException
from langchain.agents.middleware import ContextEditingMiddleware, ToolRetryMiddleware
from langchain.agents.middleware.context_editing import ClearToolUsesEdit

tool_retry = ToolRetryMiddleware(
    max_retries=1,
    retry_on=(HTTPError, TimeoutException),
    backoff_factor=0.5,
)

# Trigger context clearing well before the OpenAI server-side compaction
# threshold (100k, see ``agent_config.yaml``) so the researcher's synthesis
# turn doesn't assemble a 100k+ prompt from accumulated curl/web outputs.
# ``keep=3`` retains the three most recent tool results in full to protect
# research quality; older outputs are replaced by a ``[cleared]``
# placeholder. ``clear_at_least`` ensures meaningful compaction happens on
# trigger rather than nibbling at the edge.
context_editing = ContextEditingMiddleware(
    edits=(
        ClearToolUsesEdit(
            trigger=50_000,
            keep=3,
            clear_at_least=20_000,
        ),
    )
)
