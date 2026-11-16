from __future__ import annotations

import asyncio
import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import MemorySaver

import app.engine.workflows  # noqa: F401
from app.core.settings import settings
from app.engine.backends.factory import BACKEND_FACTORIES, FilesystemBackendType
from app.engine.backends.inprocess import InProcessFilesystemBackend
from app.engine.connect import ConnectError, ConnectReport
from app.engine.executor import execute
from app.engine.nodes.types import WorkflowName
from app.engine.schema import ResearchRequest
from tests.support.multiverse import Proof, World, check_always

AXES = {
    "source": (
        "open",
        "linked",
        "partial",
        "empty",
        "single",
        "overflow",
        "long",
        "oversize",
        "changed",
        "outside",
        "focus",
    ),
    "provider": (
        "valid",
        "none",
        "unknown",
        "self",
        "duplicate",
        "quote",
        "out_of_pool",
        "malformed",
        "provider_error",
        "embed_error",
        "embed_shape",
        "write_error",
    ),
}
PROOF = Proof(
    statement=(
        "Connect writes only a run-owned draft proposal report with eligible, "
        "quoted pairs, or fails before publication; source files remain unchanged."
    ),
    kind="always",
    seam="execute(WorkflowName.CONNECT, ResearchRequest)",
    fault_model=(
        "Source layouts, empty/oversize inputs, long excerpts, provider faults and "
        "hostile judgments. Embedding and chat boundaries are simulated. "
        "Semantic truth, concurrent writers, process crashes and model quality "
        "are outside the proof."
    ),
    axes=tuple(AXES),
    sketch="""
1. source chooses a small note graph, no notes, one note, 37 notes, long text,
   an external source edit during judgment, or an unrelated old output.
2. provider chooses valid/empty output, unknown/self/duplicate pairs, a false quote,
   malformed JSON, chat failure or embedding failure. Only external boundaries vary.
3. The public executor must preserve every preexisting file, except the edit injected
   by the provider fault. Every new report must reference source bytes, contain only
   eligible distinct pairs, expose truncation, and make at most one chat call.
Therefore every source × provider world either yields a reviewable artifact or
raises without publishing one, never silently overwriting knowledge.
""",
)


class ChatBoundary(BaseChatModel):
    scenario: str
    calls: int = 0
    payload: dict[str, Any] = {}
    change_path: Path | None = None

    @property
    def _llm_type(self) -> str:
        return "connect-test-boundary"

    def bind_tools(self, tools, **kwargs):
        assert not tools
        return self

    def _generate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs
    ) -> ChatResult:
        self.calls += 1
        assert self.calls == 1
        self.payload = json.loads(str(messages[-1].content))
        if self.change_path is not None:
            self.change_path.write_text(
                self.change_path.read_text() + "\nExternal edit."
            )
        if self.scenario == "provider_error":
            raise RuntimeError("simulated provider failure")
        content = (
            "not JSON" if self.scenario == "malformed" else json.dumps(self._output())
        )
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    def _output(self) -> dict:
        if self.scenario == "none":
            return {"bridges": []}
        a, b = self.payload["allowed_pairs"][0]
        notes = {n["id"]: n for n in self.payload["notes"]}
        bridge = {
            "a": a,
            "b": b,
            "mechanism": "A shared relation.",
            "mapping": "Roles correspond under a stated assumption.",
            "limitation": "This is a proposal, not verified equivalence.",
            "evidence_a": notes[a]["text"][:20],
            "evidence_b": notes[b]["text"][:20],
        }
        _disturb(bridge, self.scenario)
        if self.scenario == "out_of_pool":
            by_title = {note["title"]: note["id"] for note in notes.values()}
            bridge.update(a=by_title["Source 0"], b=by_title["Source 1"])
            bridge.update(
                evidence_a=notes[bridge["a"]]["text"][:20],
                evidence_b=notes[bridge["b"]]["text"][:20],
            )
        return {
            "bridges": [bridge, bridge] if self.scenario == "duplicate" else [bridge]
        }


class BrokenPublishBackend(InProcessFilesystemBackend):
    def write_text(self, path, content, encoding="utf-8"):
        result = super().write_text(path, content, encoding)
        if Path(path).suffix == ".tmp":
            raise OSError("simulated interrupted report write")
        return result


def _disturb(bridge: dict, scenario: str) -> None:
    if scenario == "unknown":
        bridge["a"] = "../../outside"
    if scenario == "self":
        bridge["b"] = bridge["a"]
    if scenario == "quote":
        bridge["evidence_a"] = "This claim is not present in the source."


def _fixture(root: Path, source: str) -> dict[Path, bytes]:
    count = {"empty": 0, "single": 1, "overflow": 37, "linked": 3, "partial": 3}.get(
        source, 2
    )
    for i in range(count):
        path = root / "notes" / f"n{i}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        body = f"Source {i} has a concrete relationship under an explicit condition."
        if source == "long":
            body += " Extra evidence." * 150
        if source == "oversize":
            body += "x" * 65536
        if source == "linked" and i < 2:
            body += f"\n[Related](/notes/n{i + 1}.md)"
        if source == "partial" and i == 0:
            body += "\n[Related](/notes/n1.md)"
        path.write_text(f"---\ntype: Zettel\ntitle: Source {i}\n---\n{body}\n")
    _prior_outputs(root, source)
    return {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _prior_outputs(root: Path, source: str) -> None:
    old = root / "outputs/report.md"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_text("Old source report is not a Connect source or result.")
    if source == "outside":
        folder = root / "a-prior"
        folder.mkdir()
        for i in range(40):
            (folder / f"{i}.md").write_text("Old evidence outside the source folder.")


def test_connect_preserves_knowledge_and_validates_model_output(tmp_path, monkeypatch):
    def holds(world: World) -> None:
        with monkeypatch.context() as patch:
            _world(tmp_path / f"w{world.index}", world, patch)

    check_always(PROOF, AXES, holds, seed=42)


def _world(root: Path, world: World, patch) -> None:
    source, provider = str(world.get("source")), str(world.get("provider"))
    before = _fixture(root, source)
    saver = MemorySaver()

    @asynccontextmanager
    async def checkpointer():
        yield saver

    patch.setattr("app.engine.executor._checkpointer", checkpointer)
    model = ChatBoundary(
        scenario=provider,
        change_path=(root / "notes/n0.md") if source == "changed" else None,
    )
    patch.setattr(settings.security, "local_vaults", [root.resolve()])
    patch.setattr(settings, "DATABASE_URL", "")
    if provider == "write_error":
        patch.setitem(
            BACKEND_FACTORIES, FilesystemBackendType.IN_PROCESS, BrokenPublishBackend
        )
    patch.setattr("app.engine.nodes.builders.agent.ChatOpenAI", lambda **kwargs: model)

    def factory():
        return InProcessFilesystemBackend(root / "assets")

    patch.setattr("app.engine.executor.assets_backend", factory)
    patch.setattr("app.engine.nodes.connect.assets_backend", factory)
    patch.setattr(httpx, "post", _embedding_boundary(provider))
    request = ResearchRequest(
        topic="x" * 1501
        if source == "focus"
        else "Find bounded structural correspondences.",
        vault={"type": "local", "path": root},
    )
    expected_error = _fails(source, provider)
    if expected_error:
        with pytest.raises(
            (ConnectError, ValueError, RuntimeError, httpx.HTTPError, OSError)
        ):
            asyncio.run(execute(WorkflowName.CONNECT, request))
        assert not list((root / "outputs/connect").glob("*.json"))
        assert not list((root / "outputs/connect").glob("*.tmp"))
    else:
        response = asyncio.run(execute(WorkflowName.CONNECT, request))
        _result(root, response, model, source)
    _preserved(before, model)
    assert model.calls <= 1
    checkpoints = list(saver.list(None))
    assert checkpoints
    assert all(not item.config["configurable"]["checkpoint_ns"] for item in checkpoints)
    assert "has a concrete relationship" not in repr(checkpoints)
    assert "ConnectOutput" not in repr(checkpoints)


def _fails(source: str, provider: str) -> bool:
    if source in ("overflow", "oversize", "focus") or provider == "write_error":
        return True
    if source in ("empty", "single"):
        return False
    if provider in ("embed_error", "embed_shape"):
        return True
    if source == "linked":
        return False
    if provider == "out_of_pool":
        return source in ("changed", "partial")
    return source == "changed" or provider not in ("valid", "none")


def _embedding_boundary(scenario):
    def post(url, *, json, **kwargs):
        if scenario == "embed_error":
            raise httpx.ConnectError("simulated embedding failure")
        if scenario == "embed_shape":
            return httpx.Response(
                200, request=httpx.Request("POST", url), json={"data": []}
            )
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "data": [
                    {"index": i, "embedding": [1.0, 0.2, 0.3]}
                    for i, _ in enumerate(json["input"])
                ]
            },
        )

    return post


def _result(root, response, model, source):
    assert response.artifacts.connect is not None
    assert response.artifacts.report is response.artifacts.sources_csv is None
    path = Path(response.artifacts.connect.absolute_path)
    assert path.is_relative_to(root / "outputs/connect")
    report = ConnectReport.model_validate_json(path.read_text())
    assert report.run_id == response.run_id
    assert report.source_count <= 36 and report.candidate_count <= 288
    assert bool(report.truncated_sources) == (source == "long")
    assert report.status == ("draft" if report.hypotheses else "empty")
    assert (report.model is not None) == bool(model.calls)
    _evidence(root, report)
    assert model.calls == (0 if source in ("empty", "single", "linked") else 1)
    assert all(
        s.path.startswith("notes/") for h in report.hypotheses for s in h.sources
    )


def _evidence(root, report):
    for hypothesis in report.hypotheses:
        assert hypothesis.type == "Hypothesis" and hypothesis.status == "draft"
        assert len({source.path for source in hypothesis.sources}) == 2
        for source in hypothesis.sources:
            raw = (root / source.path).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == source.sha256
            assert source.quote in raw.decode()


def _preserved(before, model):
    for path, raw in before.items():
        if model.calls and path == model.change_path:
            assert path.read_text() == raw.decode() + "\nExternal edit."
        else:
            assert path.read_bytes() == raw
