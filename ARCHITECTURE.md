# ARCHITECTURE.md — obsidian-agent

> **Purpose.** This document is the authoritative mental model for the
> `obsidian-agent` codebase. Every AI agent and human contributor MUST read it
> before answering architecture questions, designing features, reviewing code,
> or producing non-trivial patches. Do not infer structure from filenames alone
> — consult this file for the *why* behind each boundary.
>
> **Canonical status.** Treat this document as source-of-truth for
> responsibilities and cross-module contracts. If code contradicts this
> document, either the code drifted (update the code) or this document drifted
> (update the document in the same PR). Both must be reconciled — silence is
> not acceptable.

---

## 1. TL;DR

`obsidian-agent` is a **LangGraph-orchestrated deep-research pipeline** served
over FastAPI. A client POSTs a research topic; a sequence of LLM agents
(Researcher → Summarizer → Zettelkasten → Persist) produces a markdown report,
atomic Zettel notes, a Polars CSV of sources, and durable memory files that
seed future runs. Postgres checkpoints the graph. Arize Phoenix captures OTEL
traces.

**Primary request path:**

```text
POST /api/v1/workflows/run/{workflow_name}
  → app.api.v1.workflows.run_workflow
  → app.engine.executor.execute
  → app.engine.registry.get_workflow(name, checkpointer)
  → CompiledStateGraph.ainvoke(state, context=ResearchContext)
      ├─ researcher  → writes: research_notes, key_insights, sources, reasoning
      ├─ summarizer  → writes: report.md
      ├─ zettelkasten → writes: .vault/*.md
      └─ persist     → writes: outputs/sources.csv, .memories/*.md
  ← final ResearchState
```

**Entry points in order of likely relevance:**

| File | Role |
|---|---|
| `app/main.py` | FastAPI app + Phoenix OTEL registration + router wiring |
| `app/api/v1/workflows.py` | HTTP surface (single endpoint) |
| `app/engine/executor.py` | Single execution entry for any registered workflow |
| `app/engine/schema.py` | `ResearchState`, `ResearchContext`, `ResearchRequest` |
| `app/engine/graphs/research.py` | The full four-node pipeline graph |
| `app/core/settings.py` | Layered config (init → env → dotenv → YAML) |
| `app/core/resources/agent_config.yaml` | LLM config + per-agent system prompts |

---

## 2. System Overview (Mental Model)

The codebase is organized into **four horizontal layers** and, within the
engine layer, a set of **hexagonal adapters** behind `Protocol` contracts.

```text
┌──────────────────────────────────────────────────────────────────┐
│                       api/   (HTTP surface)                      │
│                   FastAPI routers — no business logic            │
├──────────────────────────────────────────────────────────────────┤
│                      core/   (cross-cutting)                     │
│        settings · logger · paths (constants, no I/O here)        │
├──────────────────────────────────────────────────────────────────┤
│                      engine/  (domain + orchestration)           │
│   schema · executor · registry · graphs · nodes · outputs        │
│   ┌────────── Ports (Protocols) ──────────┐                      │
│   │  backends.FilesystemBackend           │                      │
│   │  sandbox.ExecutionSandboxBackend      │                      │
│   └──────────────────────────────────────┘                       │
│   ┌────────── Adapters ───────────────────┐                      │
│   │  backends.InProcessFilesystemBackend  │                      │
│   │  sandbox.LocalSubprocessSandboxBackend│                      │
│   └──────────────────────────────────────┘                       │
│   tools/    ← agent-facing LangChain @tool functions             │
├──────────────────────────────────────────────────────────────────┤
│                     services/ (external integrations)            │
│            gh_client (PyGithub app-installation auth)            │
└──────────────────────────────────────────────────────────────────┘
```

**Key design choices** — memorize these before proposing changes:

1. **LangGraph `StateGraph` is the orchestrator.** Each agent is a *node* that
   reads/writes a shared `ResearchState` (a `TypedDict` annotated with
   `add_messages` for conversation accumulation). Edges are static.
2. **`ResearchContext` is immutable per run.** It carries read-only knobs
   (search limits, seed URLs, experiment snippets). It is a frozen slotted
   dataclass — never mutate it; set values in the request/config instead.
3. **Import-time registration.** Workflows self-register via the
   `@workflow(name)` decorator in `app/engine/registry.py`. The registry is
   populated only when `app.engine.graphs` is imported (`main.py` does this
   for its side-effect). **A new graph that isn't reachable from
   `app/engine/graphs/__init__.py` will never appear in the registry.**
4. **Agents compose LangChain built-ins + MCP + custom tools.** See
   `app/engine/tools/constants.py` — the OpenAI `web_search` and
   `code_interpreter` server-side tools plus MCP endpoints (`deepwiki`,
   `exa`) are the primary research capability. Custom `@tool` functions
   (`fetch_url`, `save_note`, `write_report`, `write_zettelkasten_notes`,
   `run_python_experiment`, `get_repo_tree`) layer app-specific behavior on
   top.
5. **Filesystem writes go through `FilesystemBackend`.** Never call
   `Path.write_text` directly from node/tool code. The backend enforces a
   sandboxed `base_path` and rejects path-escape attempts
   (`PathEscapeError`). Tar extraction uses the `strip_components` pattern
   and validates every member.
6. **Settings are layered.** Order of precedence (highest first): init
   args → env vars → `.env` → YAML (`app/core/resources/agent_config.yaml`)
   → file secrets. Nested fields use the `__` delimiter
   (e.g. `GITHUB__APP_ID`).

---

## 3. Request Lifecycle

```text
             ┌─────────────────────────────────────────────┐
  Client ──► │  FastAPI   POST /api/v1/workflows/run/...   │
             └─────────────────────┬───────────────────────┘
                                   │  ResearchRequest (pydantic)
                                   ▼
             ┌─────────────────────────────────────────────┐
             │  executor.execute(workflow_name, request)   │
             │  • AsyncPostgresSaver checkpointer          │
             │  • load_memories(.memories/)                │
             │  • build initial ResearchState + Context    │
             │  • get_workflow(name, checkpointer)         │
             └─────────────────────┬───────────────────────┘
                                   │
                                   ▼
   ┌───────────────────────────────────────────────────────────────┐
   │  CompiledStateGraph.ainvoke(state, context=ctx)               │
   │                                                               │
   │   START ─► researcher ─► summarizer ─► zettelkasten ─► persist│
   │                                                              │
   │   researcher   : create_agent(model=ChatOpenAI, tools=[...], │
   │                   response_format=ProviderStrategy(…))       │
   │                    → streams messages + updates              │
   │   summarizer   : same shape; TOOLS=[write_report]            │
   │   zettelkasten : same shape; TOOLS=[write_zettelkasten_notes]│
   │   persist      : plain Python node; writes sources.csv +     │
   │                   memory markdown via FilesystemBackend      │
   └───────────────────────────────┬───────────────────────────────┘
                                   │
                                   ▼
             ┌─────────────────────────────────────────────┐
             │           final ResearchState (dict)        │
             └─────────────────────────────────────────────┘
```

---

## 4. Directory Sitemap

Every entry below follows the pattern: **path — one-line responsibility**,
followed (for interesting modules) by what to read and what to avoid.

### `app/`

```text
app/
├── __init__.py
├── main.py                       # FastAPI app, lifespan (Phoenix OTEL), root route
├── api/
│   └── v1/
│       ├── router.py             # APIRouter assembly for v1
│       └── workflows.py          # POST /workflows/run/{workflow_name}
├── core/
│   ├── logger.py                 # loguru configuration (console + rotating file)
│   ├── paths.py                  # DEFAULT_* Path constants (.assets, .memories, .vault, outputs, .logs)
│   ├── settings.py               # pydantic-settings root (Settings) + sub-configs
│   └── resources/
│       └── agent_config.yaml     # LLMConfig + per-agent system prompts (loaded by YamlConfigSettingsSource)
├── engine/
│   ├── executor.py               # async execute(workflow_name, request) — the only run entrypoint
│   ├── registry.py               # @workflow(name) decorator + get_workflow/list_workflows
│   ├── schema.py                 # ResearchState, ResearchContext, ResearchRequest, SearchQuery
│   ├── outputs.py                # Pydantic response schemas (ResearcherOutput, SummarizerOutput, ZettelkastenOutput)
│   ├── backends/                 # Filesystem hexagon (Protocol + adapter + factory + errors)
│   │   ├── protocol.py           # FilesystemBackend Protocol — the contract
│   │   ├── inprocess.py          # InProcessFilesystemBackend (sandboxed local fs)
│   │   ├── factory.py            # FilesystemBackendType enum + lru_cached get_filesystem_backend
│   │   └── errors.py             # FilesystemBackendError hierarchy (PathEscapeError, …)
│   ├── sandbox/                  # Code-execution hexagon
│   │   ├── protocol.py           # ExecutionSandboxBackend Protocol
│   │   ├── local.py              # LocalSubprocessSandboxBackend (subprocess + timeout)
│   │   └── models.py             # ExecutionResult + ExecutionBackendType enum
│   ├── graphs/                   # StateGraph builders — decorator-registered
│   │   ├── research.py           # Full 4-node research pipeline
│   │   └── agents.py             # Single-node standalone workflows (researcher/summarizer/zettelkasten)
│   ├── nodes/                    # Per-node logic (agent factories + persist)
│   │   ├── researcher.py         # create_researcher_agent()
│   │   ├── summarizer.py         # create_summarizer_agent()
│   │   ├── zettelkasten.py       # create_zettelkasten_agent()
│   │   ├── persist.py            # persist_artifacts(state) — plain function node
│   │   ├── types.py              # Workflow/NodeName StrEnum (node + workflow identifiers)
│   │   └── builders/
│   │       └── agent.py          # build_agent_executor + run_agent_executor (invoke vs. stream)
│   ├── tools/                    # LangChain @tool functions given to agents
│   │   ├── constants.py          # OPENAI_TOOLS (web_search, code_interpreter) + MCP_TOOLS (deepwiki, exa)
│   │   ├── io.py                 # save_note, write_report, write_zettelkasten_notes + persist helpers
│   │   ├── search.py             # call_brave_search, call_exa_search, call_exa_context + query builders
│   │   ├── web.py                # fetch_url (Jina Reader → markdown)
│   │   ├── sandbox.py            # run_python_experiment (wraps LocalSubprocessSandboxBackend)
│   │   ├── github.py             # get_repo_tree (wraps GitHubRepositoryService)
│   │   └── middleware.py         # ToolRetryMiddleware + ContextEditingMiddleware (defined, not yet wired)
│   └── middleware/               # (currently empty) — reserved for future LangChain middleware
└── services/
    └── gh_client/
        ├── auth.py               # get_github_client — lru_cached PyGithub app-installation client
        ├── repo.py               # GitHubRepositoryService.get_tree / .shallow_clone (tarball → backend)
        └── types.py              # SnapshotResult TypedDict
```

### Project root

```text
.
├── ARCHITECTURE.md               # this file
├── AGENTS.md                     # agent operating contract (delegates to this doc)
├── PLAN.md                       # product spec (PRD-lite)
├── TASKS.md                      # one-off setup task for agent tooling
├── README.md                     # minimal local-run instructions
├── pyproject.toml                # uv / ruff / deps (py>=3.13, langgraph, langchain-openai, polars, modal, …)
├── uv.lock
├── justfile                      # recipes: run, fmt, up, phoenix, db-up, clean
├── docker-compose.yaml           # app + postgres + phoenix stack
├── Containerfile                 # uv-alpine based image
├── setup-agents.sh               # provisions .agents/ scaffold + per-IDE symlinks
└── tests/                        # pytest: backends, sandbox, gh_client, settings
```

### Artifact directories (runtime, created on demand)

| Dir | Owner | Contents |
|---|---|---|
| `.vault/` | zettelkasten node | Atomic markdown notes (`{slug}.md`) |
| `.memories/` | persist node | Frontmatter-rich run logs; re-read by next run via `load_memories` |
| `outputs/` | summarizer + persist | `report.md`, `sources.csv` (Polars) |
| `.logs/` | core.logger | `app.log` (rotating, 10 MB, zip-compressed, 1-week retention) |
| `.assets/` | FilesystemBackend default `base_path` | GitHub snapshots at `{owner}/{repo}@{sha}/…` |

---

## 5. Core Domain Types

Read these *before* touching any code that passes data between nodes.

### `ResearchState` (`app/engine/schema.py`)

The single shared bag passed between nodes. `TypedDict` — LangGraph updates it
by merging node return values.

| Field | Type | Producer | Consumer |
|---|---|---|---|
| `messages` | `Annotated[list[AnyMessage], add_messages]` | all agents | all agents |
| `topic` | `str` | executor (from request) | researcher |
| `search_query` | `SearchQuery \| None` | executor | search tools |
| `memories` | `list[str]` | executor (`load_memories`) | researcher (as context) |
| `research_notes` | `list[str]` | researcher | summarizer, persist |
| `experiments` | `list[str]` | researcher | summarizer |
| `code_context` | `list[str]` | researcher | summarizer |
| `sources` | `list[dict[str,str]]` | researcher | summarizer, persist |
| `report` | `str` | summarizer | zettelkasten |
| `zettelkasten_notes` | `list[dict[str,str]]` | zettelkasten | — |
| `reasoning` | `list[str]` | researcher | persist |
| `key_insights` | `list[str]` | researcher | persist |
| `backend` | `FilesystemBackend` | DI (runtime) | tools via `ToolRuntime` |
| `gh_client` | `Github` | DI (runtime) | `get_repo_tree` tool |

### `ResearchContext` (frozen dataclass)

Immutable per-run config surfaced into nodes via `Runtime[ResearchContext]`.
Fields: `search_limit`, `exa_search_type`, `fetch_code_context`, `seed_urls`,
`experiment_snippets`. **Never mutate.** If a node needs to "change" context,
emit a new state field instead.

### `ResearchRequest` (Pydantic, `extra="forbid"`)

HTTP request body. Strict: unknown fields raise 422. Fields: `topic` (≥3
chars), `seed_urls`, `experiment_snippets`, `search` (optional
`SearchQuery`).

### `FilesystemBackend` (Protocol)

The filesystem port. All persistent writes in node/tool code **must** flow
through this. The `InProcessFilesystemBackend` enforces the `base_path`
sandbox and rejects `..` traversal via `PathEscapeError`. Tar extraction
validates every member and supports `strip_components` like `tar --strip`.

### `ExecutionSandboxBackend` (Protocol)

Code-execution port. Today: `LocalSubprocessSandboxBackend` shells out to
`python -c`. A Modal-backed implementation is in scope (see `test_modal.py`).

### Output schemas (`app/engine/outputs.py`)

`ResearcherOutput`, `SummarizerOutput`, `ZettelkastenOutput` — bound to the
agents via `ProviderStrategy(...)` so OpenAI returns structured JSON matching
these Pydantic models. Changing a field here is a breaking change for the
corresponding system prompt.

---

## 6. Configuration

Settings resolve in this priority order
(`Settings.settings_customise_sources`):

1. **Init kwargs** — highest precedence (tests)
2. **Environment variables** — nested via `__` (e.g. `GITHUB__APP_ID=123`)
3. **`.env`** — dotenv file
4. **YAML** — `app/core/resources/agent_config.yaml`
5. **File secrets**

`Settings` groups:

- `github: GithubConfig | None` — `app_id`, `private_key` (SecretStr),
  `installation_id`. App-installation auth is the **only** supported method.
- `llm: LLMConfig | None` — `model` (required), reasoning knobs,
  `use_responses_api`, streaming flags, passthrough `model_kwargs`. `extra="allow"`.
- `agents: AgentsConfig | None` — nested `researcher`/`summarizer`/`zettelkasten`
  prompt blocks. Loaded from YAML.
- `workflow: WorkflowConfig` — `search_limit`, `exa_search_type`,
  `fetch_code_context`.
- `filesystem: FilesystemConfig` — `backend_type`, `base_path`.
- **Paths** — `MEMORIES_DIR`, `VAULT_DIR`, `OUTPUT_DIR`, `LOGS_DIR`.
- **API keys** — `BRAVE_SEARCH_API_KEY`, `EXA_API_KEY`, `JINA_API_KEY`.

Anything else in `.env` is silently ignored (`extra="ignore"`).

---

## 7. Runtime Topology

`docker-compose.yaml` composes three services on a single bridge network:

| Service | Image | Purpose | Port |
|---|---|---|---|
| `app` | built from `Containerfile` (uv-alpine) | FastAPI via uvicorn | 8000 |
| `db` | `postgres:alpine` | LangGraph checkpointer (`AsyncPostgresSaver`) | 5432 |
| `phoenix` | `arizephoenix/phoenix:latest` | OTEL collector + UI | 6006 / 4317 |

`justfile` targets: `just run` (local dev), `just up` (full stack via podman
compose), `just phoenix`, `just db-up`, `just fmt`, `just clean`.

---

## 8. External Dependencies

| Concern | Library / Service | Where |
|---|---|---|
| LLM | OpenAI (Chat completions + Responses API) | `langchain-openai.ChatOpenAI` in `builders/agent.py` |
| Orchestration | `langgraph` + `langchain` | everywhere in `engine/` |
| Checkpointing | `langgraph-checkpoint-postgres` | `executor.execute` |
| Built-in tools | OpenAI `web_search`, `code_interpreter` | `tools/constants.py: OPENAI_TOOLS` |
| MCP tools | `deepwiki`, `exa` | `tools/constants.py: MCP_TOOLS` |
| Web search | Brave, Exa | `tools/search.py` |
| URL → Markdown | Jina Reader (`r.jina.ai`) | `tools/web.py` |
| Sandboxed code exec | subprocess (local), Modal (planned) | `sandbox/local.py`, `test_modal.py` |
| GitHub | PyGithub (App-installation auth) | `services/gh_client/` |
| Tabular sources | Polars | `tools/io.py: write_sources` |
| Telemetry | Arize Phoenix / OpenInference instrumentations | `main.py: lifespan`, `pyproject.toml [dependency-groups].observability` |
| Logging | Loguru | `core/logger.py` |
| Config | pydantic-settings (YAML + dotenv) | `core/settings.py` |

---

## 9. Extension Points (Cookbook)

### Add a new agent node

1. Define a structured-output schema in `app/engine/outputs.py`.
2. Create `app/engine/nodes/<agent>.py` exporting `create_<agent>_agent()`
   that returns a node callable. Mirror the existing pattern:
   `build_agent_executor(...)` + `run_agent_executor(...)`.
3. Add a `Workflow`/`NodeName` enum entry in `app/engine/nodes/types.py`.
4. Wire it into a graph in `app/engine/graphs/research.py` (or create a new
   graph module).
5. If you added a new graph module, import it from
   `app/engine/graphs/__init__.py` so its `@workflow` decorator runs.
6. Update the system prompt in `app/core/resources/agent_config.yaml` and the
   corresponding `AgentsConfig` field in `app/core/settings.py`.

### Add a new tool

1. Add a `@tool` function under `app/engine/tools/`.
2. If it writes to disk, pull `backend: FilesystemBackend = runtime.state["backend"]`
   — do **not** open paths directly.
3. Import and append it to the relevant agent's `TOOLS` list in
   `app/engine/nodes/<agent>.py`.

### Add a new filesystem backend (e.g. S3, Modal volume)

1. Implement `FilesystemBackend` in a new module under
   `app/engine/backends/`. Honor the `base_path` sandbox invariant.
2. Add an enum member to `FilesystemBackendType` in
   `app/engine/backends/factory.py`.
3. Register it in `BACKEND_FACTORIES`.
4. Add tests mirroring `tests/backends/test_inprocess_backend.py`.

### Add a new execution sandbox (e.g. Modal)

1. Implement `ExecutionSandboxBackend` in a new `app/engine/sandbox/<name>.py`.
2. Add an enum member to `ExecutionBackendType` in
   `app/engine/sandbox/models.py`.
3. Add a selector (by config) in `tools/sandbox.py` or introduce a factory
   analogous to `backends/factory.py`.

### Add a new workflow

1. Create a module in `app/engine/graphs/`.
2. Decorate the builder with `@workflow("<name>")`.
3. Import from `app/engine/graphs/__init__.py`.
4. Call via `POST /api/v1/workflows/run/<name>`.

---

## 10. Invariants & Non-obvious Rules

- **State is a `TypedDict`, not a class.** Don't add methods; add helper
  functions beside it.
- **`ResearchContext` is frozen.** Don't reach for `setattr` — create a new
  instance at the executor layer if you need different values.
- **Filesystem sandbox is a security boundary, not a convenience.** Every
  new writer must consume `FilesystemBackend`. Direct `open()` / `Path.write_*`
  calls inside `nodes/` or `tools/` are a bug.
- **`@workflow` registration is import-time.** New graphs invisible to
  `app/engine/graphs/__init__.py` will silently not register. Tests
  exercising `get_workflow(name, …)` catch this.
- **PyGithub client is process-cached** via `lru_cache(maxsize=1)` in
  `gh_client/auth.py`. Config changes take effect only on process restart or
  explicit `clear_github_client()`.
- **GitHub archives are content-addressed.** `shallow_clone` resolves ref →
  commit SHA first, names the snapshot `{owner}/{repo}@{sha}`, and skips
  when the directory is non-empty. Never rename that path format — the
  skip-cache depends on it.
- **Logging config is loaded on first import of `core/logger`.** Changing
  `LOG_LEVEL` after import has no effect on handlers already attached.
- **Phoenix `register()` runs in the FastAPI lifespan** with
  `project_name="code-reviewer"` (historical). If renaming, coordinate with
  any external Phoenix project dashboards.
- **`SearchQuery` typed dict is used both by the HTTP request and the
  search-tool query builder.** Changing its shape is a three-way break
  (API, state, tools).

---

## 11. Testing Map

| Test file | Validates |
|---|---|
| `tests/backends/test_inprocess_backend.py` | `InProcessFilesystemBackend` read/write/move/delete, path-escape rejection, tar extraction with `strip_components` |
| `tests/sandbox/test_local_backend.py` | `LocalSubprocessSandboxBackend` stdout capture; `format_execution_result` stderr/empty-output branching |
| `tests/test_gh_client_repo.py` | `get_tree` caches per commit SHA; `shallow_clone` skips when snapshot dir is populated |
| `tests/test_settings.py` | `FilesystemConfig.backend_type` defaults to a supported enum value |

Agent pipeline behavior (nodes, graphs, executor) is **not** covered by
tests yet — treat this gap as high priority when touching node logic.

---

## 12. In-flight Refactors (Read the Git Log Before Trusting These)

As of this document's writing, the following reorganizations are in progress.
If you see contradictions between filesystem state and this section, prefer
the filesystem and update this file.

- **Hexagonal split.** `backends/` and `sandbox/` are new packages that
  replaced ad-hoc disk/subprocess code. New code must go through the
  `Protocol` ports.
- **Nodes/builders split.** `nodes/builders/agent.py` centralizes
  agent-executor construction. Avoid duplicating `create_agent` wiring in
  new node modules.
- **`app/services/gh_client/`** replaced an older `app/services/github/`
  module (deleted in the current branch). Always import from `gh_client`.
- **Config relocated.** `agent_config.yaml` lives under
  `app/core/resources/` (previously `app/resources/`). `core/settings.py`
  references it with a `Path(__file__).parent / "resources" / ...`.
- **`tools/middleware.py` defines `ToolRetryMiddleware` + `ContextEditingMiddleware`**
  but these are **not yet wired** into `build_agent_executor`. The
  `engine/middleware/` directory is reserved for LangChain middleware; it
  is currently empty.
- **Modal sandbox is planned, not implemented.** `test_modal.py` is an
  exploratory harness. Do not import from it.

---

## 13. Onboarding Checklist

Use this when joining the project (human or agent):

- [ ] Read Section 1 (TL;DR) and Section 2 (Mental Model).
- [ ] Trace a request end-to-end in code:
      `api/v1/workflows.py` → `executor.py` → `graphs/research.py` →
      `nodes/researcher.py` → `nodes/builders/agent.py`.
- [ ] Read `schema.py` until you can list `ResearchState` fields from memory.
- [ ] Read `app/core/resources/agent_config.yaml` to understand each
      agent's mission in its own words.
- [ ] Run `just up` (or `uv run uvicorn app.main:app --reload`) and
      inspect Phoenix at `localhost:6006`.
- [ ] Run `uv run pytest` — all tests in `tests/` should pass.
- [ ] Skim `pyproject.toml` for dependency bounds before suggesting a
      library upgrade.
- [ ] Before proposing architectural changes, re-read Sections 9 and 10.

---

## 14. How to Keep This Document Honest

- Any PR that adds, removes, or renames a file under `app/` MUST update the
  sitemap in Section 4.
- Any change to `ResearchState`, `ResearchContext`, or a `Protocol` port
  MUST update Section 5.
- Any new configuration field MUST update Section 6.
- Any new service, tool, or external dependency MUST update Section 8.
- If you finish an in-flight refactor listed in Section 12, remove that
  bullet in the same PR.

Treat this document as code. Review it like code. Let it rot and the agents
downstream will give you wrong answers with high confidence.
