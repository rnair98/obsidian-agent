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
over FastAPI. Workflow POSTs require a configured bearer token and an approved
vault; empty security configuration fails closed. A client POSTs a research topic; a sequence of LLM agents
(Vault profiler → Researcher → Summarizer → Zettelkasten → Persist) produces a markdown report,
atomic Zettel notes, a Polars CSV of sources, and durable memory files that
seed future runs. Each request must provide a local or Git-backed Obsidian vault
as the workspace base. Each run also
installs a typed agent workspace harness that surfaces a constrained shell-like
tool backed by virtual workspace mounts; durable research memories are mounted
at `/memory` for Unix-style archaeology.
Postgres checkpoints the graph when configured; otherwise each run uses a fresh
in-memory saver. Arize Phoenix captures OTEL traces.

**Primary request path:**

```text
POST /api/v1/workflows/run/{workflow_name}
  → app.api.v1.workflows.run_workflow
  → app.engine.executor.execute
  → app.engine.registry.get_workflow(name, checkpointer)
  → CompiledStateGraph.ainvoke(state, context=ResearchContext)
      ├─ vault_profiler → writes: vault_profile
      ├─ researcher  → writes: research_notes, key_insights, sources, reasoning
      ├─ summarizer  → writes: report state (no filesystem writes)
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
plus the LangGraph ``thread_id`` identifying checkpoints. There is no HTTP
resume/replay endpoint; cross-request checkpoint retention requires Postgres. Artifact
references are populated by inspecting the vault's filesystem backend after
``graph.ainvoke`` returns; only existing files are emitted. Standalone workflows do not persist artifacts,
but report/CSV references can point to pre-existing files from earlier runs.
Existence does not establish that this run wrote the artifact.

**Entry points in order of likely relevance:**

| File | Role |
|---|---|
| `app/main.py` | FastAPI app + Phoenix OTEL registration + router wiring |
| `app/api/v1/workflows.py` | HTTP surface (single endpoint) |
| `app/engine/executor.py` | Single execution entry for any registered workflow |
| `app/engine/schema.py` | `ResearchState`, `ResearchContext`, `ResearchRequest` |
| `app/engine/workflows/research.py` | The research workflow: compiles the research graph |  
| `app/engine/graphs/research.py` | The research graph (profiler, three agents, persist) |
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

1. **LangChain and LangGraph are kept primitives, not the design language.**
   The best code is no code. A line costs a reader, a test, an upgrade, and
   a failure mode. The symbols we still use are listed in the §9 adoption
   gate. A feature that needs a symbol outside that list does not start by
   integrating it. Question the assumption first. Record a replayable
   experiment before the plan (§9, "Before the plan").
2. **A workflow is not a graph.** A graph is an uncompiled `StateGraph`
   under `app/engine/graphs/`. A workflow, under `app/engine/workflows/`,
   compiles one or more graphs into the runnable the executor invokes.
   Agents are nodes inside a graph. Edges are static. `ResearchState` is
   the shared `TypedDict`; `messages` uses `add_messages`.
3. **`ResearchContext` is immutable per run.** It is a frozen slotted
   dataclass reserved for read-only runtime context passed into a node.
   Never mutate it; add explicit request/state fields only when a workflow
   actually consumes them.
4. **Import-time registration belongs to workflows.** A workflow
   self-registers via `@workflow(name)` in `app/engine/registry.py` when
   `app.engine.workflows` is imported (`main.py` does this for the
   side-effect). **A new graph is not a workflow and will not appear in
   the registry.** A workflow module that `app/engine/workflows/__init__.py`
   does not import will not appear either.
5. **Research routing differs from harness capability.** The researcher has
   OpenAI `web_search` / `code_interpreter`, DeepWiki / Exa MCP descriptors,
   and `shell`. Its default prompt routes URL reads to `exa.crawling_exa`,
   calculations to `code_interpreter`, and shell use to named prior-memory
   reads. Summarizer, Zettelkasten, and profiler specs have no tools. The
   harness still implements file operations, Jina-backed `curl`, GitHub `git`,
   and Monty-backed `python`. Prompt restrictions are not runtime permission
   boundaries. See §12 for remaining prompt inconsistencies.
6. **Filesystem writes go through `FilesystemBackend`.** Never call
   `Path.write_text` directly from node/tool code. The backend enforces a
   sandboxed `base_path` and rejects path-escape attempts
   (`PathEscapeError`). Tar extraction uses the `strip_components` pattern
   and validates every member.
7. **Workspace commands go through the harness.** The `shell` tool does not
   execute host commands. It parses a deliberately small command subset and
   dispatches to `WorkspaceSession` / `WorkspaceBackend` implementations.
   Mutable workspace objects live in a context variable installed by the
   executor, not in `ResearchState`. The executor resolves the request vault,
   mounts it at `/vault`, sets `/vault` as the shell cwd, and mounts
   `/memory` and `/outputs` to vault-local directories so agents inspect and
   write durable artifacts with ordinary file commands.
8. **Settings are layered.** Order of precedence (highest first): init
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
             │  • Postgres or per-run memory checkpointer │
             │  • resolve required request vault          │
             │  • mount vault at /vault, cwd=/vault       │
             │  • build initial ResearchState + Context    │
             │  • get_workflow(name, checkpointer)         │
             └─────────────────────┬───────────────────────┘
                                   │
                                   ▼
   CompiledStateGraph.ainvoke(state, context=ctx)
     START → vault_profiler → researcher → summarizer
           → zettelkasten → persist → END

     vault_profiler : stats + cached/LLM conventions → state.vault_profile
     researcher    : search/MCP tools + memory reads → structured findings
     summarizer    : no tools; report_content → state.report
     zettelkasten  : no tools; private profile SystemMessage → notes
     persist       : writes report.md, notes/*.md, sources.csv,
                     .memories/*.md through FilesystemBackend
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
│   ├── security.py              # fail-closed workflow bearer authentication
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
│   ├── registry.py               # @workflow(name) on workflow factories, not on graphs
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
│   │   ├── zettelkasten.py       # ZettelkastenNote + ZettelkastenOutput + DEFAULT_PROMPT + SPEC
│   │   └── vault_profiler.py     # VaultProfile + DEFAULT_PROMPT + SPEC
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
│   ├── graphs/                   # Uncompiled StateGraph builders. Not HTTP-invocable
│   │   ├── research.py           # Research pipeline graph
│   │   └── agents.py             # One-agent graphs (researcher, summarizer, zettelkasten)
│   ├── workflows/                # HTTP-invocable compositions of one or more graphs
│   │   ├── compose.py            # One graph compiles as itself; several become parent nodes
│   │   ├── research.py           # research workflow
│   │   └── agents.py             # Single-graph workflows for researcher, summarizer, zettelkasten
│   ├── nodes/                    # Per-node logic (agent factory + persist)
│   │   ├── agent.py              # make_agent_node(spec) — single factory replacing per-agent node modules
│   │   ├── vault_profiler.py     # stats, cached/LLM profile → state
│   │   ├── persist.py            # persist_artifacts(state) — side-effect node returning {} delta
│   │   ├── types.py              # NodeName + WorkflowName StrEnums (split for FastAPI validation)
│   │   └── builders/
│   │       ├── agent.py          # provider factory, executor, structured response → state
│   │       └── middleware.py     # HTTP tool retry + old tool-result context clearing
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
├── ROADMAP.md                    # target capabilities and release gates
├── TODOS.md                      # ordered implementation tasks and completion checks
├── AGENTS.md                     # agent operating contract (delegates to this doc)
├── TASKS.md                      # one-off setup task for agent tooling
├── README.md                     # minimal local-run instructions
├── pyproject.toml                # uv / ruff / deps (py>=3.13, langgraph, langchain-openai, polars, monty, …)
├── uv.lock
├── justfile                      # recipes: run, fmt, up, phoenix, db-up, clean
├── .cursor/hooks.json            # complexipy cognitive gate on agent edits (§9)
├── .cursor/skills/adversarial-qa/SKILL.md  # disassociated batch review (§11.3)
├── docker-compose.yaml           # app + postgres + phoenix stack
├── Containerfile                 # uv-alpine based image
├── setup-agents.sh               # provisions .agents/ scaffold + per-IDE symlinks
├── docs/setup-agents.md          # specification for setup-agents.sh
├── scripts/explore_modal.py      # exploratory Modal harness (not wired)
└── tests/                        # pytest; policy in tests/README.md. backends, harness, gh_client, codesearch, imports, nodes/persist
```

### Artifact directories (runtime, created on demand)

| Dir | Owner | Contents |
|---|---|---|
| `<vault>/notes/` | persist node | Atomic markdown notes (`{slug}.md`) |
| `<vault>/.memories/` | persist node + workspace mount | Frontmatter-rich run logs; mounted at `/memory`; profiler also writes hidden `.vault_profile.json` |
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
| `messages` | `Annotated[list[AnyMessage], add_messages]` | researcher, summarizer, zettelkasten | subsequent research agents |
| `topic` | `str` | executor (from request) | researcher |
| `research_notes` | `list[str]` | researcher | summarizer, persist |
| `experiments` | `list[str]` | initialized empty; no structured-output producer | — |
| `code_context` | `list[str]` | initialized empty; no structured-output producer | — |
| `sources` | `list[SourceState]` | researcher | summarizer, persist |
| `report` | `str` | summarizer | zettelkasten |
| `zettelkasten_notes` | `list[ZettelNote]` | zettelkasten | persist, response projector |
| `vault_profile` | `str` | vault_profiler | zettelkasten node |
| `reasoning` | `list[str]` | researcher | persist |
| `key_insights` | `list[str]` | researcher | persist |

Tools that need a filesystem backend or a GitHub client resolve them via
the `get_filesystem_backend(...)` / `get_github_client()` factories — they
are *not* carried in state.

### `ResearchContext` (frozen dataclass)

Immutable per-run config surfaced into nodes via `Runtime[ResearchContext]`.
It currently carries `vault: VaultLayout`, populated by
`executor.execute()` with the resolved `VaultLayout` for artifact
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
Local paths must exactly match `security.local_vaults` and be absolute,
canonical paths without symlink aliases. Git URLs must exactly match
`security.git_repositories` and use canonical public GitHub HTTPS `.git` URLs.
Validation precedes layout creation or Git execution. The HTTP workflow router
also requires `Authorization: Bearer <security.workflow_token>` before execution.
Direct engine calls enforce vault approval but have no HTTP identity boundary.

### `WorkflowRunResponse` (Pydantic, `extra="forbid"`)

The 200 OK body for ``POST /api/v1/workflows/run/{workflow_name}``. Built
by ``executor._project_run_response`` from the final ``ResearchState`` plus
the resolved ``VaultLayout`` plus the LangGraph ``thread_id``. Fields:

| Field | Type | Meaning |
|---|---|---|
| `run_id` | `str` | LangGraph ``thread_id`` identifying checkpoints; no HTTP replay endpoint |
| `workflow` | `str` | Mirror of the path param |
| `topic` | `str` | Echo of ``request.topic`` |
| `vault` | `VaultRequest` | Echo of the request's vault descriptor |
| `artifacts.report` | `ArtifactRef \| None` | ``outputs/report.md`` if present, possibly from an earlier run |
| `artifacts.sources_csv` | `ArtifactRef \| None` | ``outputs/sources.csv`` if present, possibly from an earlier run |
| `artifacts.zettels` | `list[ZettelArtifactRef]` | Per-note ``notes/<id>.md`` |
| `artifacts.memories` | `list[ArtifactRef]` | ``.memories/*.md`` newly written this run |
| `summary.key_insights` | `list[str]` | From ``state["key_insights"]`` |
| `summary.research_notes_count` | `int` | ``len(state["research_notes"])`` |
| `summary.sources_count` | `int` | ``len(state["sources"])`` |
| `summary.zettel_count` | `int` | ``len(state["zettelkasten_notes"])`` |

### Workflow and graph

A **graph** is a `StateGraph` builder in `app/engine/graphs/`. It is not
named in `WorkflowName` and it is not decorated with `@workflow`. A
**workflow** is the HTTP-invocable unit. Its factory lives in
`app/engine/workflows/`, registers with `@workflow`, and calls
`compose_graphs` with one or more graphs plus the request checkpointer.
One graph is compiled directly, so its node names stay at the top level.
Several graphs are nodes of a parent graph that shares their state schema;
the parent holds the checkpointer. An **agent** is a node inside a graph
(`AgentSpec` via `make_agent_node`), not a workflow. The researcher,
summarizer, and zettelkasten workflows each contain one agent graph. The
research workflow contains one graph of several agents, including persist.

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
`app/engine/agents/`. Ordinary agent nodes use `make_agent_node(...)` in `app/engine/nodes/agent.py`.
The research graph wraps Zettelkasten to inject the profile, while
`nodes/vault_profiler.py` owns profiling/cache behavior. All use
`build_agent_executor_from_spec()` to construct executors.

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
`ZettelkastenNote`, `VaultProfile` — defined alongside their prompts in `agents/<name>.py`
and bound to the agents via `ProviderStrategy(...)` to request provider-native
structured JSON matching these Pydantic models. Changing a field is still
a breaking change, but the prompt that describes it is rendered
automatically — no hand-maintained schema text to keep in sync.

`structured_response_delta()` explicitly maps researcher, summarizer, and
Zettelkasten outputs to state. A new output model requires a mapping or custom
node; unsupported Pydantic models currently yield an empty delta. Summarizer
`executive_summary` and `sources_used` are not projected into state. The profiler
handles its `VaultProfile` result directly.

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
- `agents: AgentsConfig | None` — `researcher`, `summarizer`, `zettelkasten`,
  and `vault_profiler` prompt and `llm` override blocks. Each `system_prompt` defaults to `""`; an
  empty string falls through to the `default_system_prompt` defined on
  the corresponding `AgentSpec` in `app/engine/agents/<name>.py`.
- **LLM precedence:** global `llm` → per-agent `llm` → spec `llm_overrides`.
  `_build_chat_model()` selects `openai` (default) or `groq` via `provider`.
  Groq strips OpenAI-specific options and uses `groq_api_key` or `GROQ_API_KEY`,
  never the global OpenAI key/base URL.
- `filesystem: FilesystemConfig` — `backend_type`, `base_path`.
- `security: SecurityConfig` — `workflow_token: SecretStr`, exact
  `local_vaults: list[Path]`, and exact `git_repositories: list[str]`.
  Environment keys are `SECURITY__WORKFLOW_TOKEN`, `SECURITY__LOCAL_VAULTS`
  and `SECURITY__GIT_REPOSITORIES`; lists use JSON. Empty token returns 503 on
  workflow requests; absent/incorrect client credentials return 401. Empty
  allowlists deny access. This is single-user shared-token access, not tenancy.
- **Paths** — `MEMORIES_DIR`, `VAULT_DIR`, `OUTPUT_DIR`, `LOGS_DIR`.
- **`DATABASE_URL`** — Postgres connection string for the LangGraph
  `AsyncPostgresSaver` checkpointer. Empty string selects a fresh `MemorySaver` for each execution.
- **`PHOENIX_ENABLED`** — when false, the FastAPI lifespan skips the
  Arize Phoenix `register()` call. Default `true`. Useful for tests and
  air-gapped runs.
- **API keys** — `JINA_API_KEY`, `GROQ_API_KEY`.
- **Logging** — `LOG_LEVEL` (default `INFO`).

Anything else in `.env` is silently ignored (`extra="ignore"`).

---

## 7. Runtime Topology

`docker-compose.yaml` composes three services on a single bridge network:

| Service | Image | Purpose | Port |
|---|---|---|---|
| `app` | built from `Containerfile` (uv-alpine) | FastAPI via uvicorn | 127.0.0.1:8000 |
| `db` | `postgres:alpine` | LangGraph checkpointer (`AsyncPostgresSaver`) | 5432, container network only |
| `phoenix` | `arizephoenix/phoenix:latest` | OTEL collector + UI | 127.0.0.1:6006; 4317 container network only |

Compose requires `POSTGRES_PASSWORD` and `SECURITY__WORKFLOW_TOKEN`; there is
no fixed password fallback. Local vaults are denied in Compose until approved
container paths and writable mounts are configured explicitly. The standalone
database recipe requires an exported password and binds only to loopback.
No source change rotates an existing database password or restarts services.
See `docs/security-access.md` for setup, migration and remaining trust boundaries.
The uv configuration keeps locked package versions; tool upgrades must be
requested explicitly instead of occurring during every run.

`justfile` targets: `just check` (the outer harness, §11.2), `just review`
(hand the diff to a fresh reviewer, §11.3), `just run` (local dev),
`just up` (full stack via podman compose), `just phoenix`, `just db-up`,
`just fmt`, `just clean`.

---

## 8. External Dependencies

| Concern | Library / Service | Where |
|---|---|---|
| LLM | OpenAI / Groq | `ChatOpenAI` / `ChatGroq` via `_build_chat_model` in `builders/agent.py` |
| Orchestration | Kept LangChain / LangGraph primitives only | §9 adoption gate. Not a license to import the rest of either package |
| Checkpointing | `langgraph-checkpoint-postgres` | `executor.execute` |
| Postgres driver | `psycopg[binary]` | required by checkpoint postgres imports |
| Built-in tools | OpenAI `web_search`, `code_interpreter` | `tools/__init__.py: OPENAI_TOOLS` |
| MCP tools | `deepwiki`, `exa` | `tools/__init__.py: MCP_TOOLS` |
| Agent workspace | Typed virtual shell harness + durable artifact/repo mounts | `app/harness/`, `engine/workspace.py`, `tools/shell.py` |
| URL → Markdown | Jina Reader (`r.jina.ai`) | `engine/workspace_commands/curl.py` via shell `curl URL` |
| Ad hoc Python analysis | Pydantic Monty through shell `python` | `engine/workspace_commands/python.py`, `harness/session.py` |
| GitHub | PyGithub (App-installation auth), surfaced to agents as `git` | `services/gh_client/`, `engine/workspace_commands/git.py` |
| Code IR parsing | standalone `tree_sitter.Parser(get_language(...))`; language pack supplies grammars | `services/codesearch/` |
| Tabular sources | Polars | `engine/artifacts/sources.py: CsvSourceStore` |
| Structured-output recovery | `json-repair` | `engine/parsing.py: parse_structured` |
| Frontmatter (YAML) | `pyyaml` | `engine/obsidian.py` — `_split_frontmatter` / `_join_frontmatter` |
| Telemetry | Arize Phoenix / OpenInference instrumentations | `main.py: lifespan`, `pyproject.toml [dependency-groups].observability` |
| Logging | Loguru | `core/logger.py` |
| Config | pydantic-settings (YAML + dotenv) | `core/settings.py` |
| Cognitive complexity | complexipy | `.cursor/hooks/complexity.py`; dev dependency; threshold 15 |
| Import boundaries | import-linter (`lint-imports`) | `pyproject.toml` `[tool.importlinter]`; `just check` |

---

## 9. Extension Points (Cookbook)

### Before the plan

Do this before a design, for human feature work and for agents. A plan
written from the first assumption is the assumption with headings.

1. Name the assumption in one sentence, and name the bias that makes it
   feel obvious. Usual biases here: the framework already imported, the
   shape of the nearest file, the first tutorial that matched the search,
   and the preference for more code.
2. Read for a conflicting account. One agreeing source is not enough.
   Official documentation, the library source, and a source that disagrees
   are the usual set. Research changes the question. It is not evidence
   that the idea works in this repository.
3. Produce the evidence with one tightly scoped experiment. State the
   hypothesis and the falsifier before the run. The falsifier is the
   observation that would kill the assumption. A result read back onto a
   hypothesis written afterward is a different experiment.
   - One assumption, one command, about as long as a focused test.
   - Hermetic. `uv run` against the committed `uv.lock`. No ambient
     credentials, no existing vault, no developer-global packages, no path
     that exists only on one machine. No network unless the question names
     the host. Randomness uses an explicit seed (§11.1).
   - Ephemeral. Scratch lives in a temporary directory and is deleted once
     the record is written. The experiment does not write the vault,
     `.assets`, Postgres, or the working tree. A service, if the question
     actually needs one, is `podman run --rm` and is gone afterward.
     `just up` is the development stack, not an experiment.
   - Reproducible. Leave a record another agent can run without asking the
     author: hypothesis, falsifier, the exact command, the inputs inline or
     as committed bytes, the seed, and the raw observation (exit code and
     the output the claim depends on). The interpretation sits under the
     observation, separate from it. Changing the command after the result
     starts a new record. The scratch directory goes away. The record stays
     with the plan.
   - Adversarial. A second agent, including one trying to refute the claim,
     reruns that record and must get the same observation. They may change
     one disturbance the record named as uncovered, and they say so. A
     quiet edit that makes the command pass is a failed replication.
4. Then run the adoption gate. A killed assumption, or a replication that
   disagrees, does not get a plan. An observation the product must keep
   becomes a proof in §11.1, replayable by its seed. The scratch command
   does not stay in the tree.

### Adoption gate

Run this after the experiment above and before the cookbook steps below.
It applies to human feature work and to agents. The best code is no code.
Every line costs a reader, a test, an upgrade, and a failure mode.

LangChain and LangGraph stay in this repository only as the primitives in
the table. Treat a new symbol from either package as untrusted until this
gate accepts it. Do not adopt a primitive because a neighboring one is
already imported, because a tutorial uses it, or because the type checker
offered it.

1. State the caller-visible outcome. No outcome, no code.
2. Prefer no new code. `ResearchState`, the harness, `FilesystemBackend`,
   and the standard library already cover files, shell commands, vault
   layout, and HTTP authentication. Use one of those when it produces the
   outcome.
3. Cut toward the simpler, streamlined, idiomatic solution in a loop.
   Idiomatic means the matching cookbook below, the standard library, or a
   module that already exists. Each pass must delete something: a module,
   a type, a dependency, a branch, or a config key. Assume another pass is
   possible until you can name what the next cut sacrifices. Stop only when
   the next cut would lose one of these, or would force a significant
   tradeoff. A significant tradeoff is a loss under decision items 1–5 in
   `AGENTS.md` (correctness, safety, debuggability, operability,
   maintainability), shown by the §9 experiment or by a §10 boundary. Taste
   is not a reason to stop.
   - Robustness: failures stay visible, and the §10 boundary still holds.
   - Intended functionality: the caller-visible outcome from step 1.
   - Extensibility: the next feature of the same kind follows the same
     cookbook, without a new framework or a second way to do this job.
   A shorter design that drops one of the three is not the solution. A
   longer design that survives another pass which keeps all three is not
   the solution either. Stopping after one pass, while a further deletion
   still keeps all three, is an unfinished gate. The author's stop is
   provisional. §11.3 is a second agent checking that claim.
   Edited Python is scored with complexipy's cognitive complexity. The
   threshold is 15, that tool's default. `.cursor/hooks/complexity.py`
   names every over-gate function after a write and, if any remain when
   the turn ends, sends them back for up to three more passes. A file is
   scored only after it is edited, so a function already over the gate is
   quiet until someone touches that file.
4. If a LangChain or LangGraph primitive is still the candidate, read its
   implementation. Name what it does, what it imports, and which of its
   behaviors an upgrade would force us to keep (checkpoint format, message
   types, tool schema, graph API). Reject it when a smaller function does
   the job.
5. Take that primitive only. Leave the adjacent API (another middleware,
   another message class, another graph helper) unused.
6. Callers outside the adapter depend on our types (`AgentSpec`,
   `ResearchState`, `WorkflowName`, `FilesystemBackend`). The adapter is a
   file already in the table. A new import site is a new adapter: add the
   file to the table, to §8 if the package is new, and to
   `tests/engine/test_framework_boundary.py` in the same change.
7. When a kept primitive is no longer the smallest way to get the outcome,
   delete the call. Do not wrap it so the dependency looks intentional.

| Primitive | Adapter | Job |
|---|---|---|
| `StateGraph`, `START`, `END`, `compile` | `app/engine/graphs/`, `app/engine/workflows/compose.py` | Static nodes and edges. `compose_graphs` compiles one graph as itself, or several as nodes of a parent |
| `BaseCheckpointSaver`, `MemorySaver`, `AsyncPostgresSaver` | `app/engine/executor.py`, `app/engine/workflows/` | `thread_id` checkpoints. Postgres when configured, otherwise one memory saver per run |
| `add_messages` | `app/engine/schema.py` | Append `messages` on `ResearchState` |
| `Runtime` | `app/engine/nodes/` | Inject frozen `ResearchContext` into a node |
| `HumanMessage`, `SystemMessage`, `AnyMessage` | `app/engine/executor.py`, `app/engine/graphs/research.py`, `app/engine/schema.py` | The conversation channel |
| `create_agent`, `ProviderStrategy` | `app/engine/nodes/builders/agent.py` | Build one executor from an `AgentSpec`; provider-side structured output |
| `tool`, `BaseTool` | `app/engine/tools/shell.py`, `app/engine/agents/types.py` | Schema for the shell tool |
| `ChatOpenAI`, `ChatGroq` | `app/engine/nodes/builders/agent.py` | The two chat adapters |
| `ContextEditingMiddleware`, `ClearToolUsesEdit`, `ToolRetryMiddleware` | `app/engine/nodes/builders/middleware.py` | Trim old tool results; retry once on HTTP timeout |
| `Runnable`, `RunnableConfig`, `StreamMode` | `app/engine/registry.py`, `app/engine/nodes/`, `app/engine/executor.py` | Invoke and stream the executor this table already builds |

### Add a new agent node

1. Create `app/engine/agents/<agent>.py` containing **everything for the
   agent in one file**:
   - The Pydantic output schema(s).
   - A `DEFAULT_PROMPT` string. Embed `$output_format` where you want the
     compact schema description injected.
   - A `SPEC: AgentSpec[OutputModel] = AgentSpec(name=..., output_schema=...,
     default_system_prompt=DEFAULT_PROMPT, tools=(...,))`.
   - Add `# ruff: noqa: E501` if the prompt prose exceeds 88 chars.
2. Add the name to `AgentName` in `agents/types.py` and a `NodeName` in
   `app/engine/nodes/types.py`. Add a `WorkflowName` only in the same change
   as a workflow that runs this agent. A node name is not a workflow name.
3. Add an `AgentPromptConfig` field and `prompt_for` case in `AgentsConfig`.
   Add output-to-state handling in `structured_response_delta`, `AgentRunResult`,
   and `ResearchState`, or handle the result in a custom node.
4. Wire the spec into a graph with `make_agent_node(SPEC, log_streams=...)`
   from `app.engine.nodes.agent`. Use a custom node only for behavior the
   spec cannot express, such as the research graph's private profile message.
5. A workflow that should run the graph imports the builder from
   `app/engine/workflows/`. Importing `app.engine.graphs` registers nothing.

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

### Add a new graph

1. Add a builder under `app/engine/graphs/` that returns an uncompiled
   `StateGraph`. Do not decorate it with `@workflow` and do not add a
   `WorkflowName` for it.
2. Stay inside the adoption-gate table. `StateGraph`, `START`, and `END`
   are the graph APIs this cookbook uses.

### Add a new workflow

1. A workflow composes one or more graphs, and the agents those graphs run.
   It is the unit `POST /api/v1/workflows/run/<name>` invokes.
2. Add `app/engine/workflows/<name>.py`. Build the graphs and pass them to
   `compose_graphs` with the request checkpointer.
3. Decorate that factory with `@workflow(WorkflowName.<NAME>)`.
4. Import the module from `app/engine/workflows/__init__.py`. `main.py`
   imports that package. A graph that the package never reaches is not a
   registered workflow.
5. Add the `WorkflowName` entry used in step 3.
6. Keep the workflow router's `require_workflow_token` dependency. New
   privileged routes authenticate before filesystem, network, or provider
   side effects.

---

## 10. Invariants & Non-obvious Rules

- **Vault authority is server-selected.** Local vault approval is exact-path,
  not recursive root approval. Git vault URLs are exact approved public GitHub
  HTTPS URLs; empty allowlists deny both types. Workflow HTTP access has no
  unauthenticated fallback. Health/OpenAPI remain public.
- **Git vault transport is isolated.** `vaults._run_git` uses a temporary HOME,
  no inherited proxy/credential/Git overrides, no system/global config, HTTPS-only
  protocol, TLS verification, no redirects and no hooks. Cached configuration
  must pass its safe schema before reuse. Fetch targets the approved URL/ref;
  checkout detaches at `FETCH_HEAD`. Private credentialed Git vaults are unsupported.
  These controls apply to request Git vaults, not agent integrations generally;
  they are not a process-wide network firewall. Approved vaults and caches must
  not be concurrently mutable by hostile local users.
- **State is a `TypedDict`, not a class.** Don't add methods; add helper
  functions beside it.
- **`ResearchContext` is frozen.** Don't reach for `setattr` — create a new
  instance at the executor layer if you need different values.
- **Filesystem sandbox is a security boundary, not a convenience.** Every
  new writer must consume `FilesystemBackend`. Direct `open()` / `Path.write_*`
  calls inside `nodes/` or `tools/` are a bug.
- **`@workflow` registration is import-time, and it is for workflows.**
  A graph builder does not register. A workflow module omitted from
  `app/engine/workflows/__init__.py` silently does not register.
  `WorkflowName` and `list_workflows()` are the same set.
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
- **Vault and repository assets have separate roots.** `resolve_vault()` roots
  the backend at the requested vault (or managed Git vault under
  `settings.filesystem.base_path/.vaults/<hash>`). Run artifacts use
  `runtime.context.vault.backend`; repository snapshots use `assets_backend()`
  under `.assets`. The default `artifacts_backend()` is not the request vault.
- **An agent's schema, prompt, tools, and per-agent LLM overrides live
  in the same file** under `app/engine/agents/<name>.py` as a single
  `SPEC: AgentSpec[...]`. Never split them. Graphs wire the spec into
  ordinary executors via `make_agent_node(SPEC, log_streams=...)`; custom
  profile handling lives in `nodes/vault_profiler.py` and `graphs/research.py`.
- **Prompts use `$output_format` for schema injection.** Do not paste
  hand-written schema descriptions into prompts — they will silently
  drift from the Pydantic model. `AgentSpec.system_prompt()` interpolates
  the placeholder via `render_output_format()`.
- **Per-request prompt placeholders flow through `get_workflow(..., prompt_context=...)`.**
  `AgentSpec.system_prompt(context)` uses `Template.safe_substitute`, so
  any `$placeholder` in a prompt can be filled by per-run context plumbed
  through `executor.execute → get_workflow → create_research_workflow →
  build_research_graph → make_agent_node → build_agent_executor_from_spec`.
  Current placeholders
  beyond `$output_format`:
  - `$prior_memories` — `executor._render_prior_memories(vault)` emits a
    cold-vs warm-vault hint so the researcher doesn't probe `/memory` via
    shell on every run.

  Unknown `$placeholders` are left intact by `safe_substitute`. One-agent
  graph builders do not accept `prompt_context` or run the profiler.
- **Vault profiling is the first research graph node.** It writes the rendered
  `<vault_profile>` block to state. Only the research graph's Zettelkasten
  wrapper injects it into a private `SystemMessage`; shared messages stay
  unchanged. Stats inspect direct Markdown children of `notes/`, sampling up
  to eight notes. Empty vaults skip the LLM. Qualitative profiles are cached
  at `.memories/.vault_profile.json` keyed only by note count; edits preserving
  that count do not invalidate the summary. Invocation failure falls back to
  deterministic stats and default conventions.
- **Artifact paths are shared across runs.** Persistence overwrites
  `outputs/report.md` and `outputs/sources.csv`. Note IDs are sanitized and
  duplicates get numeric suffixes within one run; prior-run notes can still
  be overwritten. The response projector mirrors these filename rules.
- **`ProviderStrategy(...)` is the primary structured-output mechanism.**
  `parse_structured()` exists as a fallback for seams that receive a raw
  string (tool args, persisted artifacts, non-OpenAI providers). Do not
  route the agent's primary output through `parse_structured` — you would
  lose Phoenix's structured-output trace attributes.

---

## 11. Testing Map

Policy: [tests/README.md](tests/README.md). State the promise as a `Proof` (§11.1)
and check it across `tests/support/multiverse.py`. Do not add example
assertions that restate a helper. Model-output scoring stays in the eval
fixtures in `TODOS.md` / `ROADMAP.md`, outside this map. The door is
`just check` (§11.2).

### 11.1 Proofs and the multiverse

`tests/support/multiverse.py` is the local stand-in for an
[Antithesis](https://antithesis.com/docs/introduction/how_antithesis_works/)
run. Antithesis grows a tree of timelines by varying inputs and faults, then
searches that multiverse for a break in a stated property. An
[always property](https://antithesis.com/docs/concepts/properties_assertions/properties/)
is refuted by one counterexample and is not proved by passing worlds. A
sometimes property fails until one world witnesses it. Their run is a
deterministic hypervisor. This suite does not have that hypervisor, and it
does not search thread interleavings, clocks, or network partitions. Name
those in `fault_model` when they are uncovered.

A world is one assignment of the proof's axes. `worlds()` uses the full
product when it has at most `limit` (default 256) members. Above that it
draws `limit` worlds from `Random(seed)`. The seed and the world printed on
failure are the replay key.

`Proof` fields:

| Field | Role |
|---|---|
| `statement` | The promise, in a sentence a caller would recognize. |
| `kind` | `always` or `sometimes`. |
| `seam` | The public function, route, or command the worlds drive. |
| `fault_model` | Disturbances the claim survives, and those it does not cover. |
| `axes` | Independent choices that define a world. The mapping passed to the checker must be this tuple, in this order. |
| `sketch` | Numbered premises and a conclusion line that starts with `Therefore`. The sketch must mention every axis. It is reviewed, not machine-checked, beyond those two constraints. |

`check_always` runs `holds` on every world and fails on the first raise.
`check_sometimes` fails when `witness` never returns true. Include one world
that must be accepted and one that must be rejected. The worked case is
`tests/backends/test_sandbox_multiverse.py`: path shape × `resolve`/`write_text`.

### 11.2 The outer harness

`just check` runs, in order, `ruff check` on `app/`, `tests/`, and
`.cursor/hooks`, then `pyright`, `lint-imports`, and `pytest`. There is no
CI workflow. This recipe is the left edge. `OpenResearch/`, `feynman/`, and
`docs/research/` are separate trees and are outside this door.

`pyright` stays on `app/harness` and `tests/harness`. Strict checking of
`app/engine` reports 77 diagnostics, mostly unknown types from LangChain.
Widen `include` when that count is zero.

`[tool.importlinter]` forbids the edges named in each contract. A failure
prints that contract. The repair is the cookbook in §9.

`tests/support/sensors.py` flags direct `open()` / `Path.write_*` under
`app/engine/nodes` and `app/engine/tools`. `backend.write_text` is the
allowed call. The backend package is not scanned. The same module flags a
`@workflow` graph, and a workflow module that `app/engine/workflows/__init__.py`
does not import. Each rule has a fixture under
`tests/support/sensors/fixtures/` that must fail the rule.

complexipy runs from `.cursor/hooks.json` on files edited in the current
conversation. It is not a `just check` step: six existing functions are
already over its threshold of 15.

The compiled path `vault_profiler → researcher → summarizer → zettelkasten →
persist` with a stub model stays outside `just check`.

### 11.3 Adversarial review

`just check` does not decide that a batch is lean enough. After it is
green, a second agent reviews the batch. That agent did not make the
edits. Start it with `.cursor/skills/adversarial-qa/SKILL.md` and no
summary of intent. It reads `git status` and `git diff` itself. `just
review` prints that instruction and the diff stat.

This review is the next pass of the §9 simplification loop, done by an
agent that does not share the author's bias. The report is one line per
cut, in the shape the skill defines: location, a tag (`delete`, `stdlib`,
`native`, `yagni`, `shrink`), what to cut, and what replaces it. A cut
counts only when it keeps robustness, the caller-visible outcome, and
extensibility. The list ends with `net: -<N> lines possible.` A negative
net means the batch is not done. `Lean already. Ship.` is the stop, and
that line names the sacrifice the next cut would make. Breaks of §10, the
§11.2 sensors, or an experiment record are separate `break:` lines. The
author answers a line with a shorter diff or with that named sacrifice.
Restating the plan does not close a line.

The review is not a `just check` step.



| Test file | Validates |
|---|---|
| `tests/backends/test_inprocess_backend.py` | `InProcessFilesystemBackend` read/write/move/delete, path-escape rejection, tar extraction with `strip_components` |
| `tests/backends/test_sandbox_multiverse.py` | always: `resolve` / `write_text` stay in the sandbox or raise `PathEscapeError` without writing outside, across path shape × operation; sometimes: a relative write is accepted |
| `tests/support/test_multiverse.py` | checker contracts: seeded replay, counterexample message, sometimes fails closed, proof axes match the run |
| `tests/backends/test_factory.py` | every `FilesystemBackendType` has a factory, and the configured default is one of them |
| `tests/test_gh_client_repo.py` | `get_tree` caches per commit SHA; `shallow_clone` skips when snapshot dir is populated |
| `tests/services/test_codesearch_parser.py` | language detection, Python IR extraction, and snapshot skip heuristics for vendor/generated/binary files |
| `tests/test_imports.py` | `app.main` loads; `WorkflowName` equals the registered workflows; tools import |  
| `tests/engine/test_compose_graphs.py` | One graph keeps its nodes; several graphs share one state; an empty composition is rejected |  
| `tests/engine/test_framework_boundary.py` | LangChain / LangGraph imports stay in the §9 adapter files |
| `tests/hooks/test_complexity_hook.py` | complexipy cognitive gate: a nested canary is sent back; a straight function is quiet |
| `tests/support/test_sensors.py` | direct writes in nodes/tools, `@workflow` only on imported workflow modules, graphs do not register |
| `tests/engine/test_artifacts.py` | `MarkdownMemoryStore`, `CsvSourceStore` formatting and write behavior |
| `tests/engine/test_executor_response.py` | Persisted artifact response projection and path handling |
| `tests/engine/test_vaults.py` | local/Git vault approval, transport/config isolation and standard vault layout |
| `tests/engine/test_obsidian.py` | `ObsidianVaultOperations` list/read/create/append/search/tags/backlinks/properties + symlink-cycle guard |
| `tests/engine/test_parsing.py` | `parse_structured` recovery stages (strict → fence strip → balanced extract → `json_repair`) |
| `tests/engine/test_curl_command.py` | `CurlCommand` URL → Jina Reader translation and unsupported-flag handling |
| `tests/engine/test_git_command.py` | `GitCommand` `ls-tree` / `clone` argument parsing and `gh_client` delegation |
| `tests/engine/test_python_command.py` | `python -c` and `python script.py` Monty-backed shell execution |
| `tests/engine/agents/test_spec.py` | `AgentSpec.system_prompt` YAML-override resolution + `parse` delegation |
| `tests/engine/agents/test_schema_prompt.py` | every `AgentName` renders its schema, fields, and descriptions into the system prompt |
| `tests/engine/agents/test_structured_delta.py` | Pydantic structured-output → `ResearchState` delta merging contract |
| `tests/nodes/test_persist.py` | `persist_artifacts` writes sources and memory artifacts end-to-end against a tmp filesystem |
| `tests/api/test_workflows.py` | bearer authentication before execution; authenticated routing validation and bad vault → 400 |
| `tests/api/test_security_config.py` | nested security settings, OpenAPI authentication declaration and development port restrictions |
| `tests/harness/` | Typed workspace core, shell tool adapter, and executor/agent wiring |

LangGraph executor end-to-end behavior with a stub LLM (full
`vault_profiler → researcher → summarizer → zettelkasten → persist` traversal through
the compiled graph) is still uncovered. `tests/api/test_workflows.py`
exercises only the request/routing surface, not graph traversal.

---

## 12. In-flight Refactors (Read the Git Log Before Trusting These)

This section records remaining integration work and known inconsistencies.
Reconcile it with the current code when changing these contracts.

**Research-system planning (not implemented):** the source-grounded
[Feynman audit](docs/research/feynman-audit.md) and
[OpenResearch audit](docs/research/openresearch-audit.md) inform the
[roadmap](ROADMAP.md).
It proposes shared run/evidence contracts, safe vault publication, and later
authorized experiment execution so both CLIs can eventually be retired. These
are target capabilities, not current APIs or permission changes. The existing
virtual shell remains non-host execution; any experiment runner needs a separate
explicit capability boundary and corresponding updates to §§5, 9 and 10.

Node consolidation, artifact stores, graph-based vault profiling, and the
OpenAI/Groq factory are implemented (see §§2–10). Remaining integration work:

- **Researcher prompt versus harness behavior.** The default prompt forbids
  shell fetching/analysis and incorrectly describes shell `curl` as raw host
  networking. `workspace_commands/curl.py` actually calls Jina Reader; the
  virtual harness dispatches shell commands. The prior-memory manifest also
  suggests `ls /memory` on overflow while the default prompt forbids `ls`.
  These are code/prompt inconsistencies, not alternative runtime contracts.
- **Tool surface.** Keep workflow persistence in `nodes/persist.py` and
  `engine/artifacts/`. Workspace commands remain implemented when default
  prompts route elsewhere. Do not add direct REST-shaped, fetch-shaped, or
  experiment-shaped tools. Command changes must update `CommandSpec`,
  registration, shell docstring, grammar tests, and unsupported-flag tests.
- **Obsidian-semantic operations.** `app/engine/obsidian.py`
  (`ObsidianVaultOperations`) has dedicated tests and provides a library for headless
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
      `api/v1/workflows.py` → `executor.py` → `workflows/research.py` →
      `graphs/research.py` → `nodes/agent.py` (`make_agent_node`) →
      `nodes/builders/agent.py`
      (`build_agent_executor_from_spec`) → `agents/researcher.py` (`SPEC`).
- [ ] Read `schema.py` until you can list `ResearchState` fields from memory.
- [ ] Read `agents/<name>.py` for default prompts/tools and
      `app/core/resources/agent_config.yaml` for runtime overrides.
- [ ] Run `just up` (or `uv run uvicorn app.main:app --reload`) and
      inspect Phoenix at `localhost:6006`.
- [ ] Read `tests/README.md`, then run `just check`. §11.2 lists what it runs.
- [ ] After `just check` is green, hand the batch to a new agent using
      §11.3. Do not review your own diff.
- [ ] Skim `pyproject.toml` for dependency bounds before suggesting a
      library upgrade.
- [ ] Before proposing a feature, follow §9: question the assumption, leave
      a replayable experiment record, then the adoption gate. Re-read
      Sections 9 and 10.

---

## 14. How to Keep This Document Honest

- Any PR that adds, removes, or renames a file under `app/` MUST update the
  sitemap in Section 4.
- Any change to `ResearchState`, `ResearchContext`, or a `Protocol` port
  MUST update Section 5.
- Any new configuration field MUST update Section 6.
- Any new service, tool, or external dependency MUST update Section 8.
- Any new LangChain or LangGraph import site or symbol MUST pass the §9
  adoption gate and update that section's kept-primitive table and
  `tests/engine/test_framework_boundary.py` in the same change. Removing a
  kept primitive updates the same three places.
- Any change to what the suite protects, or to the testing policy, MUST
  update Section 11 and `tests/README.md` together.
- If you finish an in-flight refactor listed in Section 12, remove that
  bullet in the same PR.

Treat this document as code. Review it like code. Let it rot and the agents
downstream will give you wrong answers with high confidence.
