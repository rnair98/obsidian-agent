from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, TypeAlias, TypedDict

from langchain_core.tools import BaseTool

AgentName: TypeAlias = Literal["researcher", "summarizer", "zettelkasten"]
AgentTool: TypeAlias = BaseTool | Callable[..., Any] | dict[str, Any]


class ToolSearchSpec(TypedDict):
    type: Literal["tool_search"]
    execution: Literal["server"]


class WebSearchSpec(TypedDict):
    type: Literal["web_search"]


class CodeInterpreterContainerSpec(TypedDict):
    type: Literal["auto"]
    memory_limit: str


class CodeInterpreterSpec(TypedDict):
    type: Literal["code_interpreter"]
    container: CodeInterpreterContainerSpec


class McpApprovalNeverSpec(TypedDict):
    tool_names: list[str]


class McpApprovalSpec(TypedDict):
    never: McpApprovalNeverSpec


class McpToolSpec(TypedDict):
    type: Literal["mcp"]
    server_label: str
    server_url: str
    require_approval: McpApprovalSpec


OpenAIToolSpec: TypeAlias = ToolSearchSpec | WebSearchSpec | CodeInterpreterSpec
