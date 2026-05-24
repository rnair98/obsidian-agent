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
seed future runs. Each request must provide a local or Git-backed Obsidian vault
as the workspace base. Each run also
installs a typed agent workspace harness that surfaces a constrained shell-like
tool backed by virtual workspace mounts; durable research memories are mounted
at `/memory` for Unix-style archaeology.
Postgres checkpoints the graph. Arize Phoenix captures OTEL traces.

**Primary request path:**

```text
POST /api/v1/workflows/run/{workflow_name}
  → app.api.v1.workflows.run_workflow
  → app.engine.executor.execute
  → app.engine.registry.get_workflow(name, checkpointer)
  → CompiledStateGraph.ainvoke(state, context=ResearchContext)
      ├─ researcher  → writes: research_notes, key_insights, sources, reasoning
      ├─ summarizer  → writes: report.md
      ├─ zettelkasten → writes: zettelkasten_notes state
      └─ persist     → writes: vault notes, outputs, .memories
  → app.engine.executor._project_run_response (ResearchState → WorkflowRunResponse)
  ← WorkflowRunResponse  (run_id, vault, artifacts.{report, sources_csv,
                          zettels, memories}, summary)
```

The raw ``ResearchState`` is intentionally NOT exposed to clients — it
carries internal LangGraph plumbing (full message history, per-node
reasoning accumulators) and would be a brittle public contract. The HTTP
boundary returns a typed ``WorkflowRunResponse`` (see ``app/engine/schema.py``)
that points clients at every artifact the workflow materialized in the vault
plus the LangGraph ``thread_id`` they can use for checkpoint replay. Artifact
references are populated by inspecting the vault's filesystem backend after
``graph.ainvoke`` returns; only files that actually exist are emitted, so
standalone agent workflows (researcher/summarizer/zettelkasten) legitimately
return empty artifact slots.

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
│   │  harness.WorkspaceBackend             │                      │
│   └──────────────────────────────────────┘                       │
│   ┌────────── Adapters ───────────────────┐                      │
│   │  backends.InProcessFilesystemBackend  │                      │
│   │  workspace_commands.PythonCommand     │                      │
│   └──────────────────────────────────────┘                       │
│   tools/    ← agent-facing LangChain @tool functions             │
│   harness/  ← typed virtual workspace + fake shell core          │
├──────────────────────────────────────────────────────────────────┤
│                     services/ (external integrations)            │
│   gh_client (PyGithub app-installation auth) ·                   │
│   codesearch (tree-sitter IR parsing over local snapshots)       │
└──────────────────────────────────────────────────────────────────┘
```

**Key design choices** — memorize these before proposing changes:

1. **LangGraph `StateGraph` is the orchestrator.** Each agent is a *node* that
   reads/writes a shared `ResearchState` (a `TypedDict` annotated with
   `add_messages` for conversation accumulation). Edges are static.
2. **`ResearchContext` is immutable per run.** It is a frozen slotted
   dataclass reserved for read-only runtime context passed through LangGraph.
   Never mutate it; add explicit request/state fields only when a workflow
   actually consumes them.
3. **Import-time registration.** Workflows self-register via the
   `@workflow(name)` decorator in `app/engine/registry.py`. The registry is
   populated only when `app.engine.graphs` is imported (`main.py` does this
   for its side-effect). **A new graph that isn't reachable from
   `app/engine/graphs/__init__.py` will never appear in the registry.**
4. **Agents compose LangChain built-ins + MCP + Unix-like custom tools.** See
   `app/engine/tools/__init__.py` — the OpenAI `web_search` and
   `code_interpreter` server-side tools plus MCP endpoints (`deepwiki`,
   `exa`) are the primary research capability. Custom `@tool` functions are
   intentionally small: the `shell` adapter is the only project-defined
   LangChain tool. Artifact CRUD, URL-to-markdown fetching, GitHub repository
   data, and ad hoc Python analysis are surfaced through the shell's
   Unix-like `/outputs`, `/vault`, `/memory`, `/repos`, `curl`, `git`, and
   `python` contracts rather than bespoke note/report/fetch/GitHub/experiment
   tools.
5. **Filesystem writes go through `FilesystemBackend`.** Never call
   `Path.write_text` directly from node/tool code. The backend enforces a
   sandboxed `base_path` and rejects path-escape attempts
   (`PathEscapeError`). Tar extraction uses the `strip_components` pattern
   and validates every member.
6. **Workspace commands go through the harness.** The `shell` tool does not
   execute host commands. It parses a deliberately small command subset and
   dispatches to `WorkspaceSession` / `WorkspaceBackend` implementations.
   Mutable workspace objects live in a context variable installed by the
   executor, not in `ResearchState`. The executor resolves the request vault,
   mounts it at `/vault`, sets `/vault` as the shell cwd, and mounts
   `/memory` and `/outputs` to vault-local directories so agents inspect and
   write durable artifacts with ordinary file commands.
7. **Settings are layered.** Order of precedence (highest first): init
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
             │  • resolve required request vault          │
             │  • mount vault at /vault, cwd=/vault       │
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
   │   summarizer   : same shape; TOOLS=[shell]                   │
   │   zettelkasten : same shape; TOOLS=[shell]                   │
   │   persist      : plain Python node; materializes report.md,  │
   │                   notes/*.md, sources.csv, .memories/*.md    │
   │                   via FilesystemBackend                      │
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
│   ├── obsidian.py               # headless optimized Obsidian-vault functions over VaultLayout
│   ├── registry.py               # @workflow(name) decorator + get_workflow/list_workflows
│   ├── schema.py                 # ResearchState, ResearchContext, ResearchRequest
│   ├── vaults.py                 # request vault resolution + standard Obsidian vault layout
│   ├── parsing.py                # parse_structured() — layered SAP-lite recovery (strict → fence-strip → yapping → json-repair)
│   ├── workspace.py              # build_workspace_session + FilesystemBackend-backed workspace mounts
│   ├── workspace_commands/       # shell command backends: curl, git, python
│   ├── agents/                   # Co-located agent definitions: schema + prompt + tools per agent
│   │   ├── spec.py               # AgentSpec[T] dataclass + system_prompt() with $output_format interpolation
│   │   ├── output_format.py      # render_output_format() — TypeScript-flavored compact schema descriptor
│   │   ├── researcher.py         # ResearcherOutput + Source + DEFAULT_PROMPT + SPEC
│   │   ├── summarizer.py         # SummarizerOutput + DEFAULT_PROMPT + SPEC
│   │   └── zettelkasten.py       # ZettelkastenNote + ZettelkastenOutput + DEFAULT_PROMPT + SPEC
│   ├── artifacts/                # Durable artifact stores + workspace mount adapter
│   │   ├── __init__.py           # public exports: MarkdownMemoryStore, CsvSourceStore, ArtifactWorkspaceBackend
│   │   ├── memory.py             # MarkdownMemoryStore (.memories research-run format)
│   │   ├── sources.py            # CsvSourceStore (sources.csv column contract)
│   │   └── mounts.py             # ArtifactWorkspaceBackend (FilesystemBackend → WorkspaceBackend)
│   ├── backends/                 # Filesystem hexagon (Protocol + adapter + factory + errors)
│   │   ├── protocol.py           # FilesystemBackend Protocol — the contract
│   │   ├── inprocess.py          # InProcessFilesystemBackend (sandboxed local fs)
│   │   ├── factory.py            # FilesystemBackendType enum + lru_cached get_filesystem_backend
│   │   └── errors.py             # FilesystemBackendError hierarchy (PathEscapeError, …)
│   ├── graphs/                   # StateGraph builders — decorator-registered
│   │   ├── research.py           # Full 4-node research pipeline
│   │   └── agents.py             # Single-node standalone workflows (researcher/summarizer/zettelkasten)
│   ├── nodes/                    # Per-node logic (agent factory + persist)
│   │   ├── agent.py              # make_agent_node(spec) — single factory replacing per-agent node modules
│   │   ├── persist.py            # persist_artifacts(state) — side-effect node returning {} delta
│   │   ├── types.py              # NodeName + WorkflowName StrEnums (split for FastAPI validation)
│   │   └── builders/
│   │       └── agent.py          # build_agent_executor_from_spec(AgentSpec) + run_agent_executor (invoke vs. stream)
│   └── tools/                    # LangChain @tool functions given to agents
│       ├── __init__.py           # OPENAI_TOOLS, MCP_TOOLS + public tool exports
│       ├── shell.py              # shell tool adapter over app.harness runtime
├── harness/
│   ├── __init__.py               # public harness exports
│   ├── commands.py               # CommandSpec dataclass + WorkspaceCommand Protocol + first_flag/unsupported_flag/render_help helpers
│   ├── fs.py                     # WorkspaceBackend Protocol + in-memory backend
│   ├── mounts.py                 # CompositeWorkspaceBackend path-prefix router
│   ├── paths.py                  # virtual POSIX path normalization
│   ├── policy.py                 # first-match permission policy
│   ├── results.py                # typed command/audit result models
│   ├── runtime.py                # current workspace contextvar + scope helper
│   └── session.py                # WorkspaceSession + constrained shell dispatcher
└── services/
    ├── codesearch/
    │   ├── __init__.py           # public exports for parsing helpers and IR models
    │   ├── languages.py          # file extension → tree-sitter language mapping
    │   ├── models.py             # FileIR / Symbol / Scope / Import Pydantic models
    │   └── parser.py             # parse_file / parse_snapshot with skip heuristics
    └── gh_client/
        ├── auth.py               # GitHubHandle (client + auth) cached factory; get_github_handle / get_github_client
        ├── repo.py               # GitHubRepositoryService.get_tree / .shallow_clone (tarball → backend)
        └── types.py              # SnapshotResult Pydantic model
```

### Project root

```text
.
├── ARCHITECTURE.md               # this file
├── AGENTS.md                     # agent operating contract (delegates to this doc)
├── TASKS.md                      # one-off setup task for agent tooling
├── README.md                     # minimal local-run instructions
├── pyproject.toml                # uv / ruff / deps (py>=3.13, langgraph, langchain-openai, polars, monty, …)
├── uv.lock
├── justfile                      # recipes: run, fmt, up, phoenix, db-up, clean
├── docker-compose.yaml           # app + postgres + phoenix stack
├── Containerfile                 # uv-alpine based image
├── setup-agents.sh               # provisions .agents/ scaffold + per-IDE symlinks
├── docs/setup-agents.md          # specification for setup-agents.sh
├── scripts/explore_modal.py      # exploratory Modal harness (not wired)
└── tests/                        # pytest: backends, harness, gh_client, codesearch, settings, imports, nodes/persist
```

### Artifact directories (runtime, created on demand)

| Dir | Owner | Contents |
|---|---|---|
| `<vault>/notes/` | persist node | Atomic markdown notes (`{slug}.md`) |
| `<vault>/.memories/` | persist node + workspace mount | Frontmatter-rich run logs; mounted at `/memory` |
| `<vault>/outputs/` | persist node + workspace mount | `report.md`, `sources.csv` (Polars) |
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
| `research_notes` | `list[str]` | researcher | summarizer, persist |
| `experiments` | `list[str]` | researcher | summarizer |
| `code_context` | `list[str]` | researcher | summarizer |
| `sources` | `list[dict[str,str]]` | researcher | summarizer, persist |
| `report` | `str` | summarizer | zettelkasten |
| `zettelkasten_notes` | `list[dict[str, object]]` | zettelkasten | — |
| `reasoning` | `list[str]` | researcher | persist |
| `key_insights` | `list[str]` | researcher | persist |

Tools that need a filesystem backend or a GitHub client resolve them via
the `get_filesystem_backend(...)` / `get_github_client()` factories — they
are *not* carried in state.

### `ResearchContext` (frozen dataclass)

Immutable per-run config surfaced into nodes via `Runtime[ResearchContext]`.
It currently carries `vault: VaultLayout`, populated by
`executor._initial_context()` with the resolved `VaultLayout` for artifact
materialization and workspace mount assembly. **Never mutate.** If a node needs
runtime context, add the field at the executor/request boundary and document
the consumer.

### `ResearchRequest` (Pydantic, `extra="forbid"`)

HTTP request body. Strict: unknown fields raise 422. Fields: `topic` (>=3
chars) and required `vault`.

`vault={"type":"local","path":"/path/to/Vault"}` uses or creates a local
Obsidian vault. `vault={"type":"git","url":"https://...","ref":"main"}`
clones/fetches a remote vault into `.vaults/<hash>/` for local read-write use;
`ref` is required and must be non-blank. This code does not commit or push.

### `WorkflowRunResponse` (Pydantic, `extra="forbid"`)

The 200 OK body for ``POST /api/v1/workflows/run/{workflow_name}``. Built
by ``executor._project_run_response`` from the final ``ResearchState`` plus
the resolved ``VaultLayout`` plus the LangGraph ``thread_id``. Fields:

| Field | Type | Meaning |
|---|---|---|
| `run_id` | `str` | LangGraph ``thread_id`` for checkpoint replay |
| `workflow` | `str` | Mirror of the path param |
| `topic` | `str` | Echo of ``request.topic`` |
| `vault` | `VaultRequest` | Echo of the request's vault descriptor |
| `artifacts.report` | `ArtifactRef \| None` | ``outputs/report.md`` if written |
| `artifacts.sources_csv` | `ArtifactRef \| None` | ``outputs/sources.csv`` if written |
| `artifacts.zettels` | `list[ZettelArtifactRef]` | Per-note ``notes/<id>.md`` |
| `artifacts.memories` | `list[ArtifactRef]` | ``.memories/*.md`` newly written this run |
| `summary.key_insights` | `list[str]` | From ``state["key_insights"]`` |
| `summary.research_notes_count` | `int` | ``len(state["research_notes"])`` |
| `summary.sources_count` | `int` | ``len(state["sources"])`` |
| `summary.zettel_count` | `int` | ``len(state["zettelkasten_notes"])`` |

``ArtifactRef`` carries both the vault-relative POSIX path (``path``) and
the backend-resolved absolute path (``absolute_path``). Refs are only
emitted if the file actually exists on the backend, so standalone agent
workflows (researcher/summarizer/zettelkasten) that don't run the persist
node legitimately return empty artifact slots. Memory files are identified
by diffing the pre- and post-run listings of ``.memories/``; the
timestamped filename produced by ``MarkdownMemoryStore`` is not
predictable from state alone.

### `FilesystemBackend` (Protocol)

The filesystem port. All persistent writes in node/tool code **must** flow
through this. The `InProcessFilesystemBackend` enforces the `base_path`
sandbox and rejects `..` traversal via `PathEscapeError`. Tar extraction
validates every member and supports `strip_components` like `tar --strip`.

### `WorkspaceBackend` / `WorkspaceSession` (`app/harness/`)

The typed virtual workspace harness. `WorkspaceBackend` exposes POSIX-like
file operations over virtual paths and returns typed entries/errors instead of
host `Path` handles. `CompositeWorkspaceBackend` routes paths by longest mount
prefix, so `/workspace`, `/memory`, `/outputs`, `/vault`, and `/repos` can use
different storage strategies while the agent sees one tree.
`app.engine.workspace` adapts the resolved request vault into workspace mounts:
`/vault` maps to the vault root, `/memory` maps to `<vault>/.memories`, and
`/outputs` maps to `<vault>/outputs`.

`WorkspaceSession` owns the current working directory, permission policy, and
command dispatch for the `shell` tool. The shell is a small grammar, not a
host shell. Commands are registered as `WorkspaceCommand` instances with a
`CommandSpec`; `help` is generated from those specs, so every command has one
metadata source. Runtime supported forms are exactly: `help [command]`, `pwd`,
`cd [path]`, `ls [path]`, `cat path`, `mkdir path`, `write path content`,
`write path -- content`, `rm path`, `mv src dst`, `cp src dst`,
`grep pattern path`, `curl URL`, `git ls-tree [-r] owner/repo`,
`git clone owner/repo [ref]`, `python -c code`, and `python path.py`.
No other flags, pipelines, redirects, shell expansion, or host commands are
supported. Unsupported flags must fail with a message naming the supported
form, so agents get corrected instead of silently drifting into normal shell
muscle memory. Use `WorkspaceSession.scratch()` for scratch-only tests and
`WorkspaceSession.with_mounts(...)` for explicit runtime mount assembly. The
session is installed per workflow run via `workspace_scope(...)` in
`executor.execute`; it is deliberately not stored in `ResearchState`.

### `ObsidianVaultOperations` (`app/engine/obsidian.py`)

Headless, deterministic subset of Obsidian's behavior over a resolved
`VaultLayout`. Reads and writes flow through a private `WorkspaceSession`
with a single `/vault` mount, so every operation honors the same
`FilesystemBackend` sandbox as the rest of the engine. Capabilities:
`list_notes`, `read`, `create` (with overwrite-guarded `NoteExistsError`),
`append`, `search` (case-folded substring with `SearchHit` results),
`tags` (counting `#tag` references), `backlinks` (matching both
`[[wikilinks]]` and relative `[markdown](links.md)` by stem/basename/path),
and YAML `properties` / `set_property` for frontmatter. Symlink-cycle
defense uses `Path.resolve(strict=False)` against a `visited` set during
the recursive walk; `.obsidian/` config is skipped.

**Status — library, not yet wired.** Currently consumed only by
`tests/engine/test_obsidian.py`. No node, tool, or graph imports it yet.
Treat it as the canonical entry point for any future agent-facing
Obsidian-semantic operation (e.g., a `vault note ...` shell subcommand or
a structured-output `materialize_notes` node). Do not duplicate its
frontmatter or wikilink parsing logic elsewhere — extend this module.

### `AgentSpec` (`app/engine/agents/spec.py`)

A frozen dataclass that bundles **schema + prompt + tools + per-agent LLM
overrides** for a single agent. One `SPEC` per agent module under
`app/engine/agents/`. Graphs wire each `SPEC` through `make_agent_node(...)`
in `app/engine/nodes/agent.py`, which builds executors via
`build_agent_executor_from_spec()` — there are no per-agent node modules.

`spec.system_prompt()` resolves YAML overrides
(`settings.agents.<name>.system_prompt`) before falling back to
`default_system_prompt`, then interpolates a `$output_format` placeholder
with `render_output_format(spec.output_schema)` so the prompt-side schema
description is always in lockstep with the Pydantic model.

`spec.parse(raw)` delegates to `parse_structured()` for seams that
receive a free-form string (tool args, persisted artifacts, future
non-OpenAI providers) — the primary structured-output mechanism remains
`ProviderStrategy(spec.output_schema)` inside `create_agent`.

### Output schemas (`app/engine/agents/<name>.py`)

`ResearcherOutput`, `SummarizerOutput`, `ZettelkastenOutput`, `Source`,
`ZettelkastenNote` — defined alongside their prompts in `agents/<name>.py`
and bound to the agents via `ProviderStrategy(...)` so OpenAI returns
structured JSON matching these Pydantic models. Changing a field is still
a breaking change, but the prompt that describes it is rendered
automatically — no hand-maintained schema text to keep in sync.

### `parse_structured` (`app/engine/parsing.py`)

Layered structured-output recovery, used as a fallback at seams where
`ProviderStrategy` isn't in play. Stages: strict → strip code fences →
extract largest balanced `{...}`/`[...]` block (yapping prefix/suffix
removal) → `json_repair`. Each attempt tags an OTel span attribute
`parse.stage` so Phoenix shows which recovery path won.

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
  prompt **override** blocks. Each `system_prompt` defaults to `""`; an
  empty string falls through to the `default_system_prompt` defined on
  the corresponding `AgentSpec` in `app/engine/agents/<name>.py`.
- `filesystem: FilesystemConfig` — `backend_type`, `base_path`.
- **Paths** — `MEMORIES_DIR`, `VAULT_DIR`, `OUTPUT_DIR`, `LOGS_DIR`.
- **`DATABASE_URL`** — Postgres connection string for the LangGraph
  `AsyncPostgresSaver` checkpointer. Empty string disables checkpointing.
- **`PHOENIX_ENABLED`** — when false, the FastAPI lifespan skips the
  Arize Phoenix `register()` call. Default `true`. Useful for tests and
  air-gapped runs.
- **API keys** — `JINA_API_KEY`.

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
| Postgres driver | `psycopg[binary]` | required by checkpoint postgres imports |
| Built-in tools | OpenAI `web_search`, `code_interpreter` | `tools/__init__.py: OPENAI_TOOLS` |
| MCP tools | `deepwiki`, `exa` | `tools/__init__.py: MCP_TOOLS` |
| Agent workspace | Typed virtual shell harness + durable artifact/repo mounts | `app/harness/`, `engine/workspace.py`, `tools/shell.py` |
| URL → Markdown | Jina Reader (`r.jina.ai`) | `engine/workspace_commands/curl.py` via shell `curl URL` |
| Ad hoc Python analysis | Pydantic Monty through shell `python` | `engine/workspace_commands/python.py`, `harness/session.py` |
| GitHub | PyGithub (App-installation auth), surfaced to agents as `git` | `services/gh_client/`, `engine/workspace_commands/git.py` |
| Code IR parsing | tree-sitter + tree-sitter-language-pack | `services/codesearch/` |
| Tabular sources | Polars | `engine/artifacts/sources.py: CsvSourceStore` |
| Structured-output recovery | `json-repair` | `engine/parsing.py: parse_structured` |
| Frontmatter (YAML) | `pyyaml` | `engine/obsidian.py` — `_split_frontmatter` / `_join_frontmatter` |
| Telemetry | Arize Phoenix / OpenInference instrumentations | `main.py: lifespan`, `pyproject.toml [dependency-groups].observability` |
| Logging | Loguru | `core/logger.py` |
| Config | pydantic-settings (YAML + dotenv) | `core/settings.py` |

---

## 9. Extension Points (Cookbook)

### Add a new agent node

1. Create `app/engine/agents/<agent>.py` containing **everything for the
   agent in one file**:
   - The Pydantic output schema(s).
   - A `DEFAULT_PROMPT` string. Embed `$output_format` where you want the
     compact schema description injected.
   - A `SPEC: AgentSpec[OutputModel] = AgentSpec(name=..., output_schema=...,
     default_system_prompt=DEFAULT_PROMPT, tools=(...,))`.
   - Add `# ruff: noqa: E501` if the prompt prose exceeds 88 chars.
2. Add a `NodeName` (and, if invocable as a workflow, `WorkflowName`) entry
   in `app/engine/nodes/types.py`.
3. Add an `AgentPromptConfig` field in `AgentsConfig` (defaults to empty
   string — the YAML key is just an override hook).
4. Wire it into a graph in `app/engine/graphs/research.py` (or create a new
   graph module) using `make_agent_node(SPEC, log_streams=...)` from
   `app.engine.nodes.agent`. **There is no per-agent node module** —
   `make_agent_node` is the single factory for all agents.
5. If you added a new graph module, import it from
   `app/engine/graphs/__init__.py` so its `@workflow` decorator runs.

### Add a new tool

1. Add a `@tool` function under `app/engine/tools/`. Prefer `async def`;
   wrap blocking third-party calls in `asyncio.to_thread`.
2. Do not add CRUD-shaped artifact tools. If the agent needs to create,
   inspect, move, or delete files, expose that through `shell` and workspace
   mounts (`/outputs`, `/vault`, `/memory`, `/repos`). Deterministic
   workflow materialization belongs in `nodes/persist.py` and
   `engine/artifacts/`.
3. Import and append it to the relevant agent's `tools` tuple on the
   `SPEC` in `app/engine/agents/<agent>.py`.

### Add a new filesystem backend (e.g. S3, Modal volume)

1. Implement `FilesystemBackend` in a new module under
   `app/engine/backends/`. Honor the `base_path` sandbox invariant.
2. Add an enum member to `FilesystemBackendType` in
   `app/engine/backends/factory.py`.
3. Register it in `BACKEND_FACTORIES`.
4. Add tests mirroring `tests/backends/test_inprocess_backend.py`.

### Extend ad hoc Python execution

1. Prefer extending `PythonCommand` in `app/engine/workspace_commands/python.py` and
   exposing behavior as a Unix-like `python` shell command.
2. Do not add a LangChain `run_python_*` tool. Agent-written analysis code
   should be ordinary workspace files or `python -c` snippets.
3. If host capabilities are needed, expose them as explicit Monty external
   functions with tests and permission checks; do not fall back to host
   subprocess execution.

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
  `project_name="obsidian-agent"`. If renaming, coordinate with any
  external Phoenix project dashboards.
- **Two filesystem backends coexist at runtime.** `settings.filesystem`
  routes agent artifacts (`.memories`, `.vault`, `outputs`) to repo root
  (`base_path=Path(".")`). `GitHubRepositoryService` resolves its own
  backend rooted at `DEFAULT_ASSETS_DIR` so snapshots stay under
  `.assets/{owner}/{repo}@{sha}`. Use the named accessors
  `artifacts_backend()` and `assets_backend()` (in
  `app.engine.backends`) instead of passing `base_path` strings around —
  the separation is load-bearing.
- **An agent's schema, prompt, tools, and per-agent LLM overrides live
  in the same file** under `app/engine/agents/<name>.py` as a single
  `SPEC: AgentSpec[...]`. Never split them. Graphs wire the spec into
  an executor via `make_agent_node(SPEC, log_streams=...)` (see
  `app/engine/nodes/agent.py`) — the executor is built once per
  factory call and reused across invocations.
- **Prompts use `$output_format` for schema injection.** Do not paste
  hand-written schema descriptions into prompts — they will silently
  drift from the Pydantic model. `AgentSpec.system_prompt()` interpolates
  the placeholder via `render_output_format()`.
- **Per-request prompt placeholders flow through `get_workflow(..., prompt_context=...)`.**
  `AgentSpec.system_prompt(context)` uses `Template.safe_substitute`, so
  any `$placeholder` in a prompt can be filled by per-run context plumbed
  through `executor.execute → get_workflow → create_research_workflow →
  make_agent_node → build_agent_executor_from_spec`. Current placeholders
  beyond `$output_format`:
  - `$prior_memories` — `executor._render_prior_memories(vault)` emits a
    cold-vs warm-vault hint so the researcher doesn't probe `/memory` via
    shell on every run.
  - `$vault_profile` — `executor._profile_vault(vault, context)` returns
    deterministic vault stats plus a qualitative summary inferred by the
    `vault_profiler` nano-class agent (one-shot pre-pass, cached at
    `<vault>/.memories/.vault_profile.json` keyed by note count). All
    three downstream agents (researcher/summarizer/zettelkasten) consume
    it so persisted artifacts match the vault's naming/structure/style
    conventions.

  Unknown `$placeholders` are intentionally left intact by
  `safe_substitute`; add a new one by (a) extending the renderer in the
  executor and (b) referencing it in the agent's prompt — no spec changes
  required.
- **Pre-graph agents are invoked directly from the executor.** The
  `vault_profiler` agent does NOT live in the research graph. It is
  invoked once per request from `executor._profile_vault` via
  `build_agent_executor_from_spec(VAULT_PROFILER_SPEC).ainvoke(...)`
  because its output is request-scoped pre-computation consumed by every
  graph agent, not a node in the workflow itself. Adding more pre-pass
  agents follows the same shape: a `SPEC` in `app/engine/agents/<name>.py`,
  a name added to `AgentName` (`agents/types.py`), a case in
  `AgentsConfig.prompt_for` (`core/settings.py`), and a `_render_*`
  helper in `executor.py`.
- **`ProviderStrategy(...)` is the primary structured-output mechanism.**
  `parse_structured()` exists as a fallback for seams that receive a raw
  string (tool args, persisted artifacts, non-OpenAI providers). Do not
  route the agent's primary output through `parse_structured` — you would
  lose Phoenix's structured-output trace attributes.

---

## 11. Testing Map

| Test file | Validates |
|---|---|
| `tests/backends/test_inprocess_backend.py` | `InProcessFilesystemBackend` read/write/move/delete, path-escape rejection, tar extraction with `strip_components` |
| `tests/test_gh_client_repo.py` | `get_tree` caches per commit SHA; `shallow_clone` skips when snapshot dir is populated |
| `tests/services/test_codesearch_parser.py` | language detection, Python IR extraction, and snapshot skip heuristics for vendor/generated/binary files |
| `tests/test_settings.py` | `FilesystemConfig.backend_type` defaults to a supported enum value |
| `tests/test_imports.py` | Import-chain smoke: `app.main` loads, registry populates, tools importable |
| `tests/engine/test_artifacts.py` | `MarkdownMemoryStore`, `CsvSourceStore` formatting and write behavior |
| `tests/engine/test_vaults.py` | local/Git vault request resolution and standard vault layout |
| `tests/engine/test_obsidian.py` | `ObsidianVaultOperations` list/read/create/append/search/tags/backlinks/properties + symlink-cycle guard |
| `tests/engine/test_parsing.py` | `parse_structured` recovery stages (strict → fence strip → balanced extract → `json_repair`) |
| `tests/engine/test_curl_command.py` | `CurlCommand` URL → Jina Reader translation and unsupported-flag handling |
| `tests/engine/test_git_command.py` | `GitCommand` `ls-tree` / `clone` argument parsing and `gh_client` delegation |
| `tests/engine/test_python_command.py` | `python -c` and `python script.py` Monty-backed shell execution |
| `tests/engine/agents/test_spec.py` | `AgentSpec.system_prompt` YAML-override resolution + `parse` delegation |
| `tests/engine/agents/test_output_format.py` | `render_output_format` TypeScript-flavored schema descriptor |
| `tests/engine/agents/test_structured_delta.py` | Pydantic structured-output → `ResearchState` delta merging contract |
| `tests/nodes/test_persist.py` | `persist_artifacts` writes sources and memory artifacts end-to-end against a tmp filesystem |
| `tests/api/test_workflows.py` | HTTP routing: unknown enum → 422, node-name workflow → 422, legacy field → 422, bad git vault → 400 |
| `tests/harness/` | Typed workspace core, shell tool adapter, and executor/agent wiring |

LangGraph executor end-to-end behavior with a stub LLM (full
`researcher → summarizer → zettelkasten → persist` traversal through
the compiled graph) is still uncovered. `tests/api/test_workflows.py`
exercises only the request/routing surface, not graph traversal.

---

## 12. In-flight Refactors (Read the Git Log Before Trusting These)

As of this document's writing, the following reorganizations are in progress.
If you see contradictions between filesystem state and this section, prefer
the filesystem and update this file.

- **Node consolidation.** The per-agent node modules
  (`nodes/researcher.py`, `nodes/summarizer.py`, `nodes/zettelkasten.py`)
  were collapsed into a single factory `make_agent_node(spec)` in
  `app/engine/nodes/agent.py`. New agents do **not** add a node module;
  they add an `AgentSpec` under `app/engine/agents/<name>.py` and the
  graph wires it via `make_agent_node(SPEC)`.
- **Artifact stores.** `app/engine/artifacts/` owns durable artifact formats:
  `MarkdownMemoryStore` writes `.memories` research-run markdown,
  `CsvSourceStore` writes `sources.csv`, and `ArtifactWorkspaceBackend`
  exposes resolved vault subtrees and repo snapshots as workspace mounts.
  Agent-facing artifact CRUD should be ordinary `shell` file commands under
  `/memory`, `/vault`, and `/outputs`, not bespoke note/report tools.
- **Tool surface.** `app/engine/tools/` contains only active LangChain tool
  wrappers and server-side tool descriptors: the workspace shell adapter in
  `tools/shell.py` plus `OPENAI_TOOLS` and `MCP_TOOLS` descriptors in
  `tools/__init__.py`. URL-to-markdown fetching is exposed through shell
  `curl`, GitHub repository data through shell `git`, and ad hoc analysis
  through shell `python` backed by Monty. Do not add direct REST-shaped,
  fetch-shaped, or experiment-shaped tools. When adding a shell command,
  implement a `WorkspaceCommand` with a `CommandSpec`, register it from
  `engine/workspace_commands/__init__.py`, and update the shell tool
  docstring, exact grammar tests, and command-specific unsupported-flag tests
  in the same change.
- **Obsidian-semantic operations.** `app/engine/obsidian.py`
  (`ObsidianVaultOperations`) is a fully test-covered library for headless
  vault reads/writes (notes, tags, backlinks, frontmatter properties), but
  no node, tool, or graph consumes it yet. When wiring it into a future
  shell subcommand (e.g., `vault note <op>`) or a deterministic
  materialization node, route through this module rather than re-rolling
  frontmatter or wikilink parsing. Remove this bullet in the PR that ships
  the first agent-facing consumer.

---

## 13. Onboarding Checklist

Use this when joining the project (human or agent):

- [ ] Read Section 1 (TL;DR) and Section 2 (Mental Model).
- [ ] Trace a request end-to-end in code:
      `api/v1/workflows.py` → `executor.py` → `graphs/research.py` →
      `nodes/agent.py` (`make_agent_node`) → `nodes/builders/agent.py`
      (`build_agent_executor_from_spec`) → `agents/researcher.py` (`SPEC`).
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
