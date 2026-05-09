"""``AgentSpec`` — co-located agent definition.

A single ``AgentSpec`` instance bundles everything that defines an
agent's contract with the LLM:

* ``output_schema``     — the Pydantic model the agent must produce
* ``default_system_prompt`` — the prompt body shipped with the code
* ``tools``             — LangChain tool callables / built-in tools
* ``llm_overrides``     — optional per-agent overrides on top of
                          ``settings.llm`` (e.g. lower temperature)

The ``settings.agents.<name>.system_prompt`` YAML value (when set)
takes precedence over the default prompt, preserving the layered
settings precedence documented in ARCHITECTURE.md \u00a76.

Prompts may reference ``$output_format`` (or ``${output_format}``);
when present it is interpolated with a token-efficient TypeScript-
flavored description of ``output_schema`` so the prompt and the
schema can never drift apart.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from string import Template
from types import MappingProxyType
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.settings import settings
from app.engine.agents.output_format import render_output_format
from app.engine.parsing import parse_structured

T = TypeVar("T", bound=BaseModel)

_EMPTY_OVERRIDES: Mapping[str, Any] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class AgentSpec(Generic[T]):
    """Frozen, hashable bundle describing one agent."""

    name: str
    output_schema: type[T]
    default_system_prompt: str
    tools: Sequence[object] = ()
    llm_overrides: Mapping[str, Any] = field(default_factory=lambda: _EMPTY_OVERRIDES)

    def output_format(self) -> str:
        """Return the schema rendered for prompt injection."""
        return render_output_format(self.output_schema)

    def system_prompt(self) -> str:
        """Return the effective system prompt with placeholders interpolated.

        YAML override (``settings.agents.<name>.system_prompt``) wins over
        ``default_system_prompt``. ``$output_format`` is then substituted.
        """
        cfg = (
            getattr(settings.agents, self.name, None)
            if settings.agents is not None
            else None
        )
        raw = (
            cfg.system_prompt
            if cfg is not None and getattr(cfg, "system_prompt", None)
            else self.default_system_prompt
        )
        if "$output_format" in raw or "${output_format}" in raw:
            return Template(raw).safe_substitute(output_format=self.output_format())
        return raw

    def llm_kwargs(self) -> dict[str, Any]:
        """Return the LLM kwargs with per-spec overrides applied last."""
        base = settings.llm.model_dump(mode="python") if settings.llm else {}
        base.update(self.llm_overrides)
        return base

    def parse(self, raw: str) -> T:
        """Recover an instance of ``output_schema`` from a free-form string."""
        return parse_structured(raw, self.output_schema)
