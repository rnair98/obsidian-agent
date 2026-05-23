from app.engine.agents.types import McpToolSpec, OpenAIToolSpec
from app.engine.tools.shell import shell

OPENAI_TOOLS: tuple[OpenAIToolSpec, ...] = (
    {"type": "tool_search", "execution": "server"},
    {"type": "web_search"},
    {
        "type": "code_interpreter",
        "container": {"type": "auto", "memory_limit": "4g"},
    },
)

MCP_TOOLS: tuple[McpToolSpec, ...] = (
    {
        "type": "mcp",
        "server_label": "deepwiki",
        "server_url": "https://mcp.deepwiki.com/mcp",
        "require_approval": {
            "never": {"tool_names": ["ask_question", "read_wiki_structure"]}
        },
    },
    {
        "type": "mcp",
        "server_label": "exa",
        "server_url": "https://mcp.exa.ai/mcp?tools=web_search_exa,get_code_context_exa,crawling_exa",
        "require_approval": {
            "never": {
                "tool_names": [
                    "web_search_exa",
                    "get_code_context_exa",
                    "crawling_exa",
                ]
            }
        },
    },
)

__all__ = [
    "MCP_TOOLS",
    "OPENAI_TOOLS",
    "shell",
]
