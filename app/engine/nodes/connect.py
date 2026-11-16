import asyncio
import json
import sqlite3
from collections.abc import Mapping
from typing import Optional
from uuid import UUID

import httpx
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from app.core.settings import settings
from app.engine.agents.connect import SPEC, ConnectOutput
from app.engine.backends import assets_backend
from app.engine.connect import (
    ConnectError,
    ConnectUnavailable,
    build_report,
    collect_candidates,
    save_report,
)
from app.engine.nodes.builders.agent import (
    AgentRunResult,
    build_agent_executor_from_spec,
)
from app.engine.nodes.types import AgentNode
from app.engine.schema import ResearchContext, ResearchState
from app.engine.similarity import http_embedder


def make_connect_node(*, prompt_context: Mapping[str, str] | None = None) -> AgentNode:
    async def node(
        state: ResearchState,
        *,
        runtime: Runtime[ResearchContext],
        config: Optional[RunnableConfig] = None,
    ) -> AgentRunResult:
        if config is None:
            raise ConnectError("Connect needs a workflow run context.")
        if len(state["topic"]) > 1500:
            raise ConnectError("Connect focus must be at most 1,500 characters.")
        run_id = str(UUID(config["configurable"]["thread_id"]))
        try:
            pool = await asyncio.to_thread(
                collect_candidates,
                runtime.context.vault,
                assets_backend(),
                http_embedder(settings.EMBEDDING_URL),
            )
        except ConnectError:
            raise
        except (httpx.HTTPError, sqlite3.Error, KeyError, ValueError) as exc:
            raise ConnectUnavailable(
                "Connect retrieval failed; check the embedding sidecar and retry."
            ) from exc
        output = ConnectOutput(bridges=[])
        model = None
        if pool.allowed_pairs:
            payload = {
                "focus": state["topic"],
                "notes": [
                    {"id": source.id, "title": source.title, "text": source.text}
                    for source in pool.notes
                ],
                "allowed_pairs": pool.allowed_pairs,
            }
            try:
                agent = build_agent_executor_from_spec(
                    SPEC, prompt_context=prompt_context, checkpointer=False
                )
                result = await agent.ainvoke(
                    input={
                        **state,
                        "messages": [HumanMessage(content=json.dumps(payload))],
                    },
                    context=runtime.context,
                    config=config,
                )
            except Exception as exc:
                raise ConnectUnavailable(
                    "Connect judgment failed; check the provider and retry."
                ) from exc
            output = result.get("structured_response")
            if not isinstance(output, ConnectOutput):
                raise ConnectError("Connect did not return a structured judgment.")
            model = str(SPEC.llm_kwargs()["model"])
        report = build_report(run_id, state["topic"], model, pool, output)
        await asyncio.to_thread(save_report, runtime.context.vault, pool, report)
        return {}

    return node
