# Code Intelligence Service — Roadmap

> **Purpose**: Give the Researcher agent a token-efficient way to understand
> medium-to-large GitHub repos without raw REST API calls or blind grepping.
>
> **Design constraint**: Local-first filesystem I/O. No storage abstractions —
> paths that work on disk today become mounted volumes (GCS/S3) in production.
> Compute-heavy phases (indexing, embedding) are written as standalone functions
> suitable for Cloud Run jobs or [Modal](https://modal.com/docs/reference).
>
> **Audience**: Human (educational) + coding agents (task-executable).
> Each slice ends with concrete deliverables, a test strategy, and an
> explicit "done when" definition.

---

## Architecture overview

```
┌─────────────────────────────────────────────────────────┐
│                    Agent API (FastAPI / MCP tools)       │  ← Phase 5+
├─────────────────────────────────────────────────────────┤
│  Query Planner  │  Fusion / Reranking                   │  ← Phase 6
├─────────────────┼───────────────────────────────────────┤
│  AST Search     │  Lexical Index  │  Semantic Index     │  ← Phases 2–4
├─────────────────┴───────────────────────────────────────┤
│  Code IR (tree-sitter parse → symbols, scopes, refs)    │  ← Phase 2
├─────────────────────────────────────────────────────────┤
│  Repo Snapshot (tarball → local tree @ commit SHA)       │  ← Phase 1
├─────────────────────────────────────────────────────────┤
│  GitHub Client (app-installation auth, PyGithub)         │  ← exists: repo.py
└─────────────────────────────────────────────────────────┘
   Storage: .agent-outputs/github/repos/<owner>/<repo>@<sha>
```

---

## Slice 1 — Repo Snapshot

**Goal**: Download a point-in-time tarball of any accessible repo and extract
it to a deterministic local path. This is the foundation everything else
builds on.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `snapshot_repo(repo_name, ref=None) → SnapshotResult` | Uses `Repository.get_archive_link("tarball", ref)` to fetch a tarball, extracts to `.agent-outputs/github/repos/<owner>/<repo>@<sha>/`. Returns a Pydantic model with `path`, `commit_sha`, `ref`, `repo_name`, `timestamp`. |
| 2 | Idempotency check | If `<owner>/<repo>@<sha>/` already exists and is non-empty, skip download. |
| 3 | `list_snapshots(repo_name=None) → list[SnapshotResult]` | Enumerate existing snapshots on disk. |
| 4 | `delete_snapshot(repo_name, sha)` | Cleanup helper. |

### File layout

```
app/services/github/
├── repo.py          # existing — GitHub client + auth
├── snapshot.py      # NEW — snapshot_repo, list/delete helpers
└── models.py        # NEW — SnapshotResult, shared Pydantic models
```

### Key decisions

- **Tarball, not clone**: No `.git` overhead. Snapshots are read-only source
  trees, not working copies. This keeps disk usage predictable and avoids
  git-specific abstractions.
- **SHA in path**: Makes snapshots content-addressable. Two downloads of the
  same commit are a no-op.
- **`ref` defaults to repo default branch**: Resolved to a concrete SHA before
  download so the path is always `@<sha>`, never `@main`.

### Test strategy

- Unit: mock `Repository.get_archive_link()`, verify extraction and path.
- Integration: real PyGithub call against a small public repo (e.g.,
  `octocat/Hello-World`), verify files on disk.

### Done when

- `snapshot_repo("octocat/Hello-World")` returns a `SnapshotResult` with a
  populated directory containing the repo's files.
- Calling it again with the same SHA is a no-op.
- `list_snapshots()` finds it. `delete_snapshot()` removes it.

---

## Slice 2 — Code IR (tree-sitter parse)

**Goal**: Parse every file in a snapshot into a canonical intermediate
representation: symbols, scopes, imports, and a line-indexed structure
suitable for downstream search.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `parse_file(path) → FileIR` | tree-sitter parse → `FileIR` with `symbols: list[Symbol]`, `scopes: list[Scope]`, `imports: list[Import]`, `lines: list[str]`, `language: str`. |
| 2 | `parse_snapshot(snapshot_path) → list[FileIR]` | Walk the snapshot tree, skip binaries/vendor, parse all supported files. |
| 3 | `FileIR`, `Symbol`, `Scope`, `Import` models | Pydantic models that capture the parse output. |
| 4 | Language detection | Map file extensions → tree-sitter language grammars. Start with Python, TypeScript/JavaScript, Go, Rust, Java. |

### File layout

```
app/services/codesearch/
├── __init__.py
├── parser.py        # parse_file, parse_snapshot
├── models.py        # FileIR, Symbol, Scope, Import
└── languages.py     # extension → language mapping, grammar loading
```

### Inspiration

- **grep-ast** (`Aider-AI/grep-ast`): `TreeContext` class walks the AST,
  tracks `scopes` (which scope each line belongs to) and `nodes` (AST nodes
  per line). We borrow this line-indexed scope model.
- **contextplus** (`ForLoopCodes/contextplus`): Extracts file skeletons,
  symbol tables, and codebase metrics from ASTs.

### Key decisions

- **Flat IR, not a graph (yet)**: Slice 2 produces per-file IR. Cross-file
  references (call graph, dependency graph) come in Slice 5.
- **Pydantic models, not dicts**: Typed, serializable, agent-friendly.
- **Skip binary/vendor/generated**: Use heuristics + `.gitignore`-style rules.

### Dependencies

- `tree-sitter` + `tree-sitter-language-pack` (or individual grammars)
- Add to `pyproject.toml`: `tree-sitter>=0.23`, `tree-sitter-language-pack`

### Test strategy

- Unit: parse a known Python file, assert expected symbols and scopes.
- Snapshot: parse a real snapshot from Slice 1, verify no crashes on mixed
  file types.

### Done when

- `parse_file("example.py")` returns a `FileIR` with correct function/class
  symbols and their line ranges.
- `parse_snapshot(snapshot_path)` successfully parses a multi-language repo
  without errors on unsupported files (they're skipped gracefully).

---

## Slice 3 — AST-Aware Search

**Goal**: Given a parsed snapshot, answer queries like "find all functions
matching `auth*`" or "show me the context around line 42 of auth.py" — with
AST-aware context (parent scopes, sibling definitions) instead of raw grep.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `search_code(snapshot_path, pattern, **filters) → list[SearchResult]` | Regex/literal search across parsed files. Returns matches with AST context (enclosing function/class, neighboring symbols). |
| 2 | `search_symbols(snapshot_path, name, kind=None) → list[Symbol]` | Lookup by symbol name/kind (function, class, method, variable). |
| 3 | `get_context(snapshot_path, file, line, radius=5) → ContextResult` | Return lines with AST-aware expansion (show full enclosing scope, not just ±N lines). |
| 4 | `SearchResult`, `ContextResult` models | Include `file`, `line`, `match`, `enclosing_symbol`, `scope_chain`, `preview`. |

### File layout

```
app/services/codesearch/
├── search.py        # search_code, search_symbols, get_context
└── models.py        # += SearchResult, ContextResult
```

### Key decisions

- **grep-ast pattern**: Match lines via regex, then expand context using the
  scope tree from `FileIR`. This gives agents the function signature + class
  hierarchy around a match, not just surrounding lines.
- **Filters**: `language`, `path_glob`, `symbol_kind` narrow results before
  search. Keeps output compact and token-efficient.
- **No index yet**: This is a scan-based search over parsed IR. Fine for
  repos up to ~50k files. Indexing comes in Slice 4.

### Test strategy

- Unit: search for a known function name, verify it returns with correct
  enclosing scope chain.
- Compare: same query via raw `grep` vs `search_code` — verify the AST
  version returns fewer, more relevant lines.

### Done when

- `search_code(snapshot, "authenticate")` returns matches with enclosing
  function/class names and a compact preview.
- `search_symbols(snapshot, "User", kind="class")` returns all class
  definitions named `User`.
- `get_context(snapshot, "auth.py", 42)` returns the full enclosing function,
  not just lines 37–47.

---

## Slice 4 — Lexical Index

**Goal**: Build an inverted index over the parsed IR so that search is O(1)
lookup instead of O(n) file scan. Enables instant exact-match, substring,
and regex-prefiltered queries.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `build_index(snapshot_path) → IndexHandle` | Tokenize all `FileIR` lines, build inverted index. Store as SQLite FTS5 database alongside the snapshot. |
| 2 | `query_index(index, query, **filters) → list[SearchResult]` | Fast retrieval using FTS5 `MATCH` with path/language/symbol-kind filters. |
| 3 | n-gram substring index | For substring queries that FTS5 can't handle natively (e.g., `"erAuth"` matching `UserAuthHandler`). |
| 4 | Index lifecycle | `rebuild_index`, `index_exists`, `drop_index`. |

### File layout

```
app/services/codesearch/
├── index.py         # build_index, query_index, index lifecycle
└── schema.sql       # FTS5 table definitions (or inline in index.py)
```

### Key decisions

- **SQLite FTS5**: Zero-infrastructure, single-file database that lives next
  to the snapshot. No Postgres or external service needed for local dev.
  Production can swap to Tantivy via the same query interface if needed.
- **Index stored at `<snapshot_path>/.codesearch.db`**: Co-located with the
  source tree. Deleting a snapshot deletes its index.
- **Trigram index for substrings**: FTS5 tokenizer handles word-boundary
  queries; a separate trigram table handles arbitrary substring matching.

### Inspiration

- **GitHub Blackbird**: Inverted token index + n-gram substring index +
  filename/path index, sharded by blob ID, with Boolean query parsing.
  ([Source](https://github.blog/engineering/architecture-optimization/the-technology-behind-githubs-new-code-search/))

### Dependencies

- `sqlite3` (stdlib) — FTS5 is included in Python's bundled SQLite on 3.13+.

### Test strategy

- Build index on a snapshot, query for known tokens, verify results match
  scan-based search from Slice 3.
- Benchmark: index build time and query latency on a ~10k file repo.

### Done when

- `build_index(snapshot)` creates a `.codesearch.db` file.
- `query_index(index, "authenticate")` returns results in <50ms for a 10k
  file repo.
- Substring query `query_index(index, "erAuth", mode="substring")` finds
  `UserAuthHandler`.

---

## Slice 5 — Symbol Graph

**Goal**: Build a cross-file graph of symbols connected by imports,
references, and structural relationships. Enables "where is this used?"
and "what depends on this?" queries.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `build_symbol_graph(snapshot_path) → SymbolGraph` | Walk all `FileIR`s, resolve import → definition edges, build reference edges from symbol usage. |
| 2 | `find_references(graph, symbol) → list[Reference]` | All usages of a symbol across files. |
| 3 | `find_dependents(graph, file_or_symbol) → list[Dependent]` | Reverse dependency traversal — "what breaks if I change this?" |
| 4 | `get_call_graph(graph, function) → CallGraph` | Approximated call graph rooted at a function. |
| 5 | `SymbolGraph`, `Reference`, `Dependent`, `CallGraph` models | Pydantic models for graph query results. |

### File layout

```
app/services/codesearch/
├── graph.py         # build_symbol_graph, find_references, find_dependents
└── models.py        # += SymbolGraph, Reference, Dependent, CallGraph
```

### Key decisions

- **networkx for prototyping**: Simple, well-documented graph library.
  Swap to a custom adjacency store if memory becomes an issue on large repos.
- **Approximated, not sound**: Static analysis without type inference. Good
  enough for navigation and impact estimation, not a compiler.
- **Stored as pickle or JSON alongside snapshot**: Same co-location pattern
  as the lexical index.

### Dependencies

- Add to `pyproject.toml`: `networkx>=3.0`

### Done when

- `find_references(graph, "UserService")` returns all files/lines that
  import or call `UserService`.
- `find_dependents(graph, "auth.py")` returns files that import from `auth.py`.

---

## Slice 6 — Semantic Retrieval

**Goal**: Add embedding-based search as a secondary recall path. Complements
exact/lexical search by finding conceptually related code even when
terminology differs.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `build_embeddings(snapshot_path) → EmbeddingIndex` | AST-aware chunking (function-level, class-level), embed with `sentence-transformers`, store in FAISS. |
| 2 | `semantic_search(index, query, top_k=10) → list[SemanticResult]` | ANN retrieval over embedded chunks. |
| 3 | Chunk metadata store | Map chunk IDs back to `(file, start_line, end_line, symbol_name)`. |
| 4 | Dedup by content hash | Identical chunks (copy-pasted code) indexed once. |

### File layout

```
app/services/codesearch/
├── embeddings.py    # build_embeddings, semantic_search
└── models.py        # += EmbeddingIndex, SemanticResult
```

### Key decisions

- **AST-aware chunking, not sliding window**: Chunk boundaries align with
  function/class definitions from `FileIR`. Produces coherent, meaningful
  chunks.
- **sentence-transformers + FAISS**: Already in the ecosystem (fastembed
  cache exists in workspace). HNSW for approximate nearest neighbor.
- **Secondary recall only**: Semantic search expands recall for fuzzy
  queries. Exact/lexical search remains the primary path.

### Dependencies

- Already available: `scipy`. Add: `sentence-transformers`, `faiss-cpu`.

### Compute note

This slice is the first candidate for offloading to Cloud Run / Modal.
Embedding generation is CPU/GPU-intensive and batch-friendly.

### Done when

- `semantic_search(index, "user authentication flow")` returns relevant
  auth-related functions even if they don't contain the word "authentication".

---

## Slice 7 — Query Planner & Fusion

**Goal**: Unify all retrieval paths behind a single query interface that
plans execution, merges results, and re-ranks.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `plan_query(query, scope) → QueryPlan` | Parse a natural-language or structured query into an execution plan (which indexes to hit, which filters to apply). |
| 2 | `execute_plan(plan) → list[FusedResult]` | Run retrieval across lexical, AST, semantic, and graph indexes. Merge via Reciprocal Rank Fusion (RRF). |
| 3 | Reranking | Optional LLM-based or cross-encoder reranking pass on top-k candidates. |
| 4 | Scope & filter rewriting | Auto-narrow by repo, path, language, symbol kind based on query context. |

### File layout

```
app/services/codesearch/
├── planner.py       # plan_query, execute_plan
├── fusion.py        # RRF merge, reranking
└── models.py        # += QueryPlan, FusedResult
```

### Inspiration

- **GitHub Blackbird**: Query rewriting + consistent result handling. Map user
  intent into a structured execution plan, not a single retrieval call.
  ([Source](https://github.blog/engineering/architecture-optimization/the-technology-behind-githubs-new-code-search/))

### Done when

- `execute_plan(plan_query("how does auth work?", repo="myorg/myapp"))`
  returns a ranked list drawing from multiple retrieval paths, with
  provenance tags showing which index contributed each result.

---

## Slice 8 — Impact Analysis

**Goal**: Given a set of changed files or symbols, estimate the blast radius —
which files, tests, and downstream consumers are affected.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `analyze_impact(graph, changed_files) → ImpactReport` | Reverse dependency traversal + affected tests ranking. |
| 2 | `validate_commit(snapshot_a, snapshot_b) → CommitValidation` | Diff two snapshots, compute impact, flag risky changes. |
| 3 | Confidence scoring | Estimate confidence based on graph completeness and static analysis limitations. |

### File layout

```
app/services/codesearch/
├── impact.py        # analyze_impact, validate_commit
└── models.py        # += ImpactReport, CommitValidation
```

### Done when

- `analyze_impact(graph, ["auth.py"])` returns a ranked list of affected
  files and test files with confidence scores.

---

## Slice 9 — Agent API

**Goal**: Expose the code intelligence system as tool endpoints consumable
by LangGraph agents (and optionally as an MCP server).

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | LangGraph tool wrappers | `@tool` functions: `search_code`, `get_symbol`, `find_references`, `get_context`, `semantic_neighbors`, `impact_analysis`, `repo_snapshot`. |
| 2 | FastAPI endpoints | REST API mirror of the tool functions for external consumers. |
| 3 | MCP server (optional) | Expose tools via MCP for use by other agents (Claude, Cursor, etc.). |

### File layout

```
app/engine/tools/codesearch.py   # LangGraph @tool wrappers
app/api/codesearch.py            # FastAPI routes
```

### Key decisions

- **Compact, structured output**: Every tool returns Pydantic models with
  `file`, `line`, `preview`, `confidence`, and `citations`. Designed for
  token-efficient agent consumption.
- **Lazy indexing**: Tools auto-build missing indexes on first query. No
  separate "indexing" step required by the agent.

### Done when

- The Researcher agent can call `search_code("authenticate", repo="org/app")`
  and receive structured, citation-rich results without any REST API calls
  to GitHub.

---

## Slice 10 — Workspace Sync & Incremental Updates

**Goal**: Avoid re-downloading and re-indexing entire repos when only a few
files changed. Merkle-tree-based diffing to detect changes and update indexes
incrementally.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | File content hashing (SHA-256) | Hash every file in a snapshot. |
| 2 | Directory Merkle tree | Hierarchical hash for fast subtree comparison. |
| 3 | Delta sync | Compare two snapshots (or snapshot vs remote HEAD), download only changed files. |
| 4 | Incremental index update | Update FTS5, symbol graph, and embeddings for only changed files. |
| 5 | Ignore rules | Respect `.gitignore` + custom `.codesearchignore`. |

### Inspiration

- **Cursor secure indexing**: Merkle trees over file content, delta
  upload/download, similarity-hash reuse for copied codebases.
  ([Source](https://cursor.com/blog/secure-codebase-indexing))

### Done when

- Updating a 10k-file snapshot where 5 files changed takes <5 seconds
  (not minutes for a full re-index).

---

## Slice 11 — Secure Sharing & Reuse

**Goal**: Allow index reuse across branches, forks, and clones without
leaking unrelated data. Privacy-safe multi-tenant index sharing.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | Workspace similarity hashing | Detect near-identical codebases (fork, branch) and reuse indexes. |
| 2 | Proof-of-possession | A workspace can only reuse an index if it can prove it has the source files (via Merkle hashes). |
| 3 | Access-scoped index reuse | Per-user and per-org index boundaries. |
| 4 | Encrypted path mapping | File paths encrypted at rest in shared indexes. |

### Inspiration

- **Cursor security model**: Proof-of-possession checks, encrypted path
  mapping, incremental refresh.
  ([Source](https://cursor.com/security))

### Done when

- Switching branches reuses 95%+ of the existing index within seconds.
- A user in org A cannot access org B's index, even if the code is similar.

---

## Slice 12 — Agent UX & Telemetry

**Goal**: Make the system trustworthy and self-improving. Agents need
confidence scores, provenance, and explanations to rely on results deeply.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | Confidence scores | Per-result confidence based on match quality, index coverage, and retrieval path. |
| 2 | Provenance & citations | Every result tagged with which index contributed it and a line-level source link. |
| 3 | Query trace | Visualization of how a query was planned and executed (for debugging). |
| 4 | Eval harness | Precision/recall benchmarks on known-good query sets. |
| 5 | Telemetry | Log missed queries, low-confidence results, and agent feedback. |

### Done when

- Agents can inspect *why* a result was returned (provenance) and *how
  confident* the system is.
- An eval harness runs nightly and tracks precision/recall over time.

---

## Implementation stack (summary)

| Layer | Choice | Rationale |
|---|---|---|
| Repo access | PyGithub (existing) | App-installation auth already wired |
| Parsing | tree-sitter + tree-sitter-language-pack | Multi-language AST, grep-ast-proven |
| Lexical index | SQLite FTS5 + trigram table | Zero-infra, co-located with snapshot |
| Symbol graph | networkx | Simple prototyping, swap later if needed |
| Semantic index | sentence-transformers + FAISS | Existing ecosystem compatibility |
| Query fusion | Reciprocal Rank Fusion | Proven merge strategy, no training needed |
| API | FastAPI (existing) + LangGraph `@tool` | Matches existing app architecture |
| Background jobs | asyncio / Modal / Cloud Run | Local-first, offload when needed |
| Storage | Filesystem paths | Mounted volumes in prod, no abstraction |

---

## Reference links

### GitHub / Blackbird
- [The technology behind GitHub's new code search](https://github.blog/engineering/architecture-optimization/the-technology-behind-githubs-new-code-search/)
- [A brief history of code search at GitHub](https://github.blog/engineering/architecture-optimization/a-brief-history-of-code-search-at-github/)

### Cursor / Secure Indexing
- [Secure codebase indexing](https://cursor.com/blog/secure-codebase-indexing)
- [Cursor security](https://cursor.com/security)

### Code Intelligence
- [grep-ast (Aider-AI)](https://github.com/Aider-AI/grep-ast) — AST-aware grep using tree-sitter
- [contextplus (ForLoopCodes)](https://github.com/ForLoopCodes/contextplus) — Codebase metrics and symbol navigation

### MCP
- [MCP servers](https://github.com/modelcontextprotocol/servers)

---

## Suggested build order

```
Slice 1: Repo Snapshot        ← start here, unblocks everything
Slice 2: Code IR              ← tree-sitter parse, core data model
Slice 3: AST-Aware Search     ← first usable search for agents
  ─── MVP: agents can snapshot a repo and search it ───
Slice 4: Lexical Index        ← performance upgrade (scan → index)
Slice 5: Symbol Graph         ← cross-file navigation
Slice 6: Semantic Retrieval   ← fuzzy/conceptual search
Slice 7: Query Planner        ← unified interface
  ─── Full code intelligence ───
Slice 8: Impact Analysis      ← change reasoning
Slice 9: Agent API            ← tool endpoints for LangGraph/MCP
Slice 10: Workspace Sync      ← incremental updates
Slice 11: Secure Sharing      ← multi-tenant index reuse
Slice 12: Agent UX            ← trust, telemetry, eval
```
