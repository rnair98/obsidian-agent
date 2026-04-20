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

## GitNexus alignment

GitNexus is not just a code-search backend. The current repository already
has a concrete product shape: a native CLI/MCP path, a browser-based Web UI,
bridge mode for reusing local indexes, multi-repo/group workflows, and an eval
harness for tool quality. This roadmap should therefore stay centered on:

- repo access and snapshotting as the ingestion boundary
- graph construction and retrieval as the core intelligence layer
- MCP/CLI tool parity with `query`, `context`, `impact`, `detect_changes`,
  `rename`, and `cypher`
- multi-repo and group-level operations, not single-repo only flows
- local-first storage with explicit browser, bridge, and native runtime paths
- evaluation and observability as first-class deliverables, not an afterthought

---

## Architecture overview

```text
┌─────────────────────────────────────────────────────────┐
│              CLI / MCP / Web UI tool surface             │  ← Phase 5+
├─────────────────────────────────────────────────────────┤
│  Query Planner  │  Fusion / Reranking  │  Eval Harness  │  ← Phase 6+
├─────────────────┼──────────────────────┼────────────────┤
│  AST Search     │  Lexical Index  │  Semantic Index     │  ← Phases 2–4
├─────────────────┴───────────────────────────────────────┤
│  Code IR (tree-sitter parse → symbols, scopes, refs)    │  ← Phase 2
├─────────────────────────────────────────────────────────┤
│  Repo Snapshot + Registry (tree @ commit SHA + metadata) │  ← Phase 1
├─────────────────────────────────────────────────────────┤
│  GitHub Client (app-installation auth, PyGithub)         │  ← exists: repo.py
└─────────────────────────────────────────────────────────┘
  Storage: local filesystem by default; bridge/native/web runtimes may
  project the same logical repo state into LadybugDB or WASM-backed stores.
```

## Roadmap shape

This document intentionally keeps the early slices focused on ingestion and
navigation primitives, then layers the GitNexus-specific delivery surfaces on
top. The practical sequence should be:

1. Make repo access and snapshotting deterministic.
2. Build a shared IR that supports graph construction and search.
3. Expose the exact tool primitives GitNexus agents need.
4. Add multi-repo, bridge, and evaluation workflows only after the core graph
  is trustworthy.

---

## Slice 1 — Repo Access & Snapshot Registry

**Goal**: Resolve accessible GitHub repos, snapshot them at a concrete commit,
and register local metadata so downstream indexing and MCP tools can operate on
stable repo identities.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `snapshot_repo(repo_name, ref=None) → SnapshotResult` | Uses `Repository.get_archive_link("tarball", ref)` to fetch a tarball, extracts to `.agent-outputs/github/repos/<owner>/<repo>@<sha>/`. Returns a Pydantic model with `path`, `commit_sha`, `ref`, `repo_name`, `timestamp`, and registry metadata. |
| 2 | Idempotency check | If `<owner>/<repo>@<sha>/` already exists and is non-empty, skip download. |
| 3 | `list_snapshots(repo_name=None) → list[SnapshotResult]` | Enumerate existing snapshots on disk and expose registry state for `list`/`status` flows. |
| 4 | `delete_snapshot(repo_name, sha)` | Cleanup helper that also unregisters the snapshot. |
| 5 | `resolve_default_ref(repo_name) → str` | Resolve default branches and symbolic refs before download so every snapshot is pinned to a commit SHA. |

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
- **Registry is authoritative**: Repo listings, status, cleanup, and group
  membership should all read from the same snapshot registry instead of
  reconstructing state ad hoc.

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
- **Production retrieval: impact-ordered + WAND pruning**: `query_index()`
  should use the highest-IDF query terms to build a targeted candidate set
  first, then apply WAND-style threshold pruning to eliminate documents that
  cannot mathematically reach top-k before fully scoring them. This keeps
  retrieval sub-linear even without clustering. Delta + variable-length
  encoding for doc IDs (4 bytes → ~1.3 bytes avg) and frequency-grouped
  postings reduce memory 50%+ at scale. (Exa achieved this on their BM25
  index across billions of documents.)

### Inspiration

- **GitHub Blackbird**: Inverted token index + n-gram substring index +
  filename/path index, sharded by blob ID, with Boolean query parsing.
  ([Source](https://github.blog/engineering/architecture-optimization/the-technology-behind-githubs-new-code-search/))
- **Exa BM25**: Impact-ordered retrieval + WAND dynamic pruning + frequency-
  grouped postings + delta encoding → 50%+ memory reduction, 10% latency
  improvement. ([Source](https://exa.ai/blog/bm25-optimization))

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

- **KuzuDB, not networkx**: KuzuDB is an embedded graph DB (MIT, C++ core,
  Python bindings, no server). Graphs are stored persistently at
  `<snapshot_path>/.graph/` — no serialization, no rebuild on every
  process start. Cypher queries work natively, which directly enables
  Slice 9's `cypher` tool without additional work. networkx has no
  persistence and no query language; KuzuDB has both. GitNexus validated
  this combination before migrating to LadybugDB solely for WASM browser
  support — which this project does not need.
- **Approximated, not sound**: Static analysis without type inference. Good
  enough for navigation and impact estimation, not a compiler.
- **Schema**: Nodes typed as `Symbol(id, name, kind, file, start_line,
  end_line, repo)`. Edges typed as `IMPORTS`, `CALLS`, `REFERENCES`,
  `DEFINES`. KuzuDB's typed schema enforces this without manual validation.

### Dependencies

- Add to `pyproject.toml`: `kuzu` (Python bindings, bundles the C++ engine)

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
| 1 | `build_embeddings(snapshot_path) → EmbeddingIndex` | AST-aware chunking (function-level, class-level), embed with `sentence-transformers`, store in a LanceDB table at `<snapshot_path>/.embeddings/`. Table columns: `chunk_id`, `file`, `start_line`, `end_line`, `symbol_name`, `language`, `repo`, `content`, `vector`. |
| 2 | `semantic_search(index, query, top_k=10, **filters) → list[SemanticResult]` | Single LanceDB query: SQL `WHERE` clause for filters (language, path_glob, symbol_kind) + vector search over matching rows. LanceDB handles filter+ANN natively — no manual pre-filter dicts. |
| 3 | Dedup by content hash | Identical chunks (copy-pasted code) indexed once. |

### File layout

```
app/services/codesearch/
├── embeddings.py    # build_embeddings, semantic_search
└── models.py        # += EmbeddingIndex, SemanticResult
```

### Key decisions

- **AST-aware chunking, not sliding window**: Chunk boundaries align with
  function/class definitions from `FileIR`. Target 900 tokens per chunk,
  15% overlap. Large functions that exceed the target are split at the
  highest-quality AST sub-boundary — scored by tree-sitter node type
  (function def > block > expression > statement) so chunks always end
  at a meaningful syntactic boundary rather than mid-expression.
- **LanceDB as the container**: LanceDB owns the table schema, SQL
  filtering, persistence, and cloud-backed storage (S3/GCS upgrade path).
  It stores vectors and chunk metadata in one table, applying SQL `WHERE`
  filters before the ANN scan — no manual pre-filter dicts. Continue IDE
  uses it for exactly this use case (code semantic search, local-first).
- **TurboQuant compression as an experiment**: Rather than using LanceDB's
  default IVF-PQ index, try pre-compressing embeddings with TurboQuant
  (rotate → Lloyd-Max scalar quantize → store codes + norm as a binary
  column) and scoring via asymmetric dot product at query time. LanceDB's
  Lance format supports custom binary columns alongside the vector column;
  the query path can fetch the binary codes and run the TurboQuant scoring
  kernel directly. If this works cleanly, it buys ~6× compression at 95%
  recall (vs PQ's ~41%) with zero codebook training — good for incremental
  indexing. **Fallback**: if the custom scoring integration is too rough,
  drop back to LanceDB's default IVF-PQ index, which is fast enough at
  repo scale and requires no extra work.
- **Prefer Matryoshka-trained embedding models**: e.g., `nomic-embed-code`
  or `jina-embeddings-v3`. Allows dimension truncation at query time for
  faster ANN with minimal recall loss.
- **Prefer Matryoshka-trained embedding models**: Models trained with
  Matryoshka representation learning (e.g., `nomic-embed-code`,
  `jina-embeddings-v3`) allow truncating embedding dimensions at query time
  (e.g., 256 of 768 dims) for faster ANN with minimal recall loss. Use
  full dimensions only for the reranking pass.
- **Secondary recall only**: Semantic search expands recall for fuzzy
  queries. Exact/lexical search remains the primary path.

### Dependencies

- Add: `sentence-transformers`, `lancedb` (Apache 2.0, embedded, no server).

### Compute note

This slice is the first candidate for offloading to Cloud Run / Modal.
Embedding generation is CPU/GPU-intensive and batch-friendly.

### Done when

- `semantic_search(index, "user authentication flow")` returns relevant
  auth-related functions even if they don't contain the word "authentication".
- Adding new chunks after a partial repo update (Slice 10) requires no
  index retraining — LanceDB supports online inserts and deletes natively.

---

## Slice 7 — Query Planner & Fusion

**Goal**: Unify all retrieval paths behind a single query interface that
plans execution, merges results, and re-ranks.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | `plan_query(query, scope, intent=None) → QueryPlan` | Classify query type (`exact` / `fuzzy` / `hybrid`), then build an execution plan (which indexes to hit, which filters to apply, which query variants to generate). Exact queries route to lexical only; fuzzy to semantic only; hybrid to both + RRF. `intent` can override routing (e.g., `"snippet"` forces lexical even on fuzzy queries). |
| 2 | `execute_plan(plan) → list[FusedResult]` | Run retrieval across selected indexes. Merge via Reciprocal Rank Fusion (RRF) — first sub-query result carries 2× weight. Each result tagged with which index contributed it. |
| 3 | BM25 confidence gate | After lexical retrieval, if results ≥ k and top BM25 score ≥ threshold *and* no `intent` override is set, skip the semantic leg entirely. Saves embedding inference on the majority of exact-match queries. |
| 4 | HyDE query variant | For `fuzzy` queries: generate a hypothetical code snippet matching the query (using the agent LLM with a prompt template), embed the snippet rather than the raw query text. Closes the vocabulary gap between natural-language queries and code tokens. Cache the generated snippet in `llm_cache`. |
| 5 | `llm_cache` table | SQLite table in `.codesearch.db` (alongside FTS5). Key = `sha256(query_text + operation_type)`. Caches HyDE snippets and reranker LLM calls — repeated queries in agentic loops pay the LLM cost once. |
| 6 | Reranking | Optional LLM-based or cross-encoder reranking pass on top-k candidates. Position-aware blending: `final_score = blend(rrf_rank, reranker_score)` with position-dependent weights. |
| 7 | Scope & filter rewriting | Auto-narrow by repo, path, language, symbol kind based on query context. |

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

## Slice 9 — LangChain Tool Surface

**Goal**: Expose the codesearch service as conventional LangChain `@tool`
functions the Researcher agent can call directly. No separate server, no
MCP, no CLI — those come later if and when the service needs to be shared
with other agents outside this process.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | LangGraph `@tool` wrappers | `search_code`, `search_symbols`, `get_context`, `find_references`, `find_dependents`, `analyze_impact`, `cypher`, `list_snapshots`. Each is a thin wrapper over the service layer with no LangChain imports in the service itself. |
| 2 | Lazy indexing | Tools auto-build missing indexes (snapshot, FTS5, KuzuDB graph, LanceDB embeddings) on first call. No separate indexing step required by the agent. |

### File layout

```
app/engine/tools/codesearch.py   # LangGraph @tool wrappers only
app/services/codesearch/         # Pure service layer — no LangChain imports
```

### Key decisions

- **Thin wrappers, pure service layer**: `@tool` functions call service
  functions directly. The service layer has no LangChain dependency. This
  is the seam that makes CLI/MCP extraction straightforward later — the
  tools just become a different calling convention over the same functions.
- **Compact, structured output**: Every tool returns Pydantic models with
  `file`, `line`, `preview`, `confidence`, and `citations`. Designed for
  token-efficient agent consumption.

### Future: CLI / MCP extraction

When the service needs to be shared across agents or processes, the
extraction path is: wrap the same service functions in a CLI entry point
(`typer` / `click`) and an MCP server. The service layer stays unchanged.
FastAPI endpoints and multi-repo bridge mode follow the same pattern.

### Done when

- The Researcher agent can call `search_code("authenticate", repo="org/app")`
  and receive structured, citation-rich results without any REST API calls
  to GitHub.
- All tools are callable from a LangGraph node with no additional setup.

---

---

> **Slices 10–12 are deferred.** The service is useful without them.
> Revisit when the agent is running against large repos in production and
> re-indexing cost becomes observable. The CLI/MCP extraction path (noted
> in Slice 9) is the natural trigger for Slices 10–11.

---

## Slice 10 — Workspace Sync & Incremental Updates *(deferred)*

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
- Embedding index handles incremental deletes: when a file is removed or
  changed, its chunk rows are deleted from the LanceDB table by `chunk_id`,
  then new chunks are inserted — no retraining, no full re-index.

---

## Slice 11 — Secure Sharing & Reuse *(deferred)*

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

## Slice 12 — Agent UX & Telemetry *(deferred)*

**Goal**: Make the system trustworthy and self-improving. Agents need
confidence scores, provenance, and explanations to rely on results deeply.

### Deliverables

| # | Item | Detail |
|---|------|--------|
| 1 | Confidence scores | Per-result confidence based on match quality, index coverage, and retrieval path. |
| 2 | Provenance & citations | Every result tagged with which index contributed it and a line-level source link. |
| 3 | Query trace | Visualization of how a query was planned and executed (for debugging). |
| 4 | Eval harness | See eval design below. Runs nightly, tracks all four metrics over time. |
| 5 | Telemetry | Log missed queries, low-confidence results, and agent feedback. |

### Eval design

Evaluate retrieval quality on four independent axes (based on Exa's WebCode
eval framework):

| Metric | What it tests | How to measure |
|---|---|---|
| **Groundedness** | Does retrieved context *contain* the correct answer? | Discriminative LLM judge — given context + gold answer, asks "is the answer present?" Never sees the synthesized response. |
| **Correctness** | Does the agent produce the right answer from context? | Generative judge — given synthesized response + gold answer. Never sees the retrieved context. |
| **Citation precision** | What fraction of returned results actually contain the answer? | Direct check over result set. |
| **E2E task pass rate** | Does an agent using this index pass unit tests in a sandbox? | Generate coding tasks requiring specific symbols from indexed repos. Run agent output in a Modal/subprocess sandbox. Check test pass rate. |

**Key principle**: measure groundedness and correctness *independently*.
Correctness scores cluster high across all retrieval qualities because the
synthesis LLM fills gaps from parametric memory — it gives no signal about
retrieval. Groundedness isolates the index. (Exa found correctness ~86%
across all providers; groundedness showed high variance and actually
differentiated them.)

**Open evals, not static fixtures**: Generate eval queries from repo
snapshots that postdate the embedding model's training cutoff. This forces
the index to actually retrieve rather than the LLM to recall from training.
Regenerate the eval set periodically rather than using a fixed benchmark
that models will eventually saturate.

### Done when

- Agents can inspect *why* a result was returned (provenance) and *how
  confident* the system is.
- Eval harness runs nightly, reporting groundedness, correctness, citation
  precision, and E2E pass rate as separate tracked metrics.

---

## Implementation stack (summary)

| Layer | Choice | Rationale |
|---|---|---|
| Repo access | PyGithub (existing) | App-installation auth already wired |
| Parsing | tree-sitter + tree-sitter-language-pack | Multi-language AST, grep-ast-proven |
| Lexical index | SQLite FTS5 + trigram table | Zero-infra, co-located with snapshot |
| Symbol graph | KuzuDB | Embedded graph DB (MIT, no server), persistent Cypher queries, typed node/edge schema; enables Slice 9 `cypher` tool without extra work |
| Semantic index | sentence-transformers + LanceDB (+ TurboQuant experiment) | LanceDB for table/filter/persistence layer; TurboQuant compression as experimental index backend (fallback: LanceDB default IVF-PQ) |
| Query fusion | Reciprocal Rank Fusion + query-type routing | Proven merge strategy; exact/fuzzy/hybrid routing avoids unnecessary index fan-out |
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

### Exa / Search Architecture
- [How we built a web-scale vector database](https://exa.ai/blog/building-web-scale-vector-db) — clustering-based ANN + inverted filter indexes; why IVF beats HNSW for filtered search (Slice 6)
- [Serving BM25 with 50% memory reduction](https://exa.ai/blog/bm25-optimization) — WAND dynamic pruning, frequency-grouped postings, delta encoding (Slice 4 production path)
- [exa-code: web context for coding agents](https://exa.ai/blog/exa-code) — code-specific retrieval model design; dense context philosophy
- [WebCode: Search Evals for Coding Agents](https://exa.ai/blog/webcode) — groundedness vs correctness, open evals, sandbox E2E eval design (Slice 12)

### Embedding Store
- [LanceDB](https://github.com/lancedb/lancedb) — embedded file-based vector DB, Apache 2.0; vectors + metadata in one Lance/Arrow table, native SQL filters, online inserts/deletes, S3/GCS upgrade path (Slice 6)
- [Continue IDE × LanceDB](https://www.lancedb.com/blog/ai-native-development-local-continue-lancedb) — case study validating LanceDB for local-first code semantic search (same use case)

### Graph Store
- [KuzuDB](https://github.com/kuzudb/kuzu) — embedded property graph DB, MIT; Cypher queries, typed schema, persistent, Python bindings (Slice 5, enables Slice 9 `cypher` tool)
- [GitNexus](https://github.com/abhigyanpatwari/GitNexus) — reference implementation using the same KuzuDB→graph pipeline for code intelligence

### Query Pipeline

- [tobi/qmd](https://github.com/tobi/qmd) — on-device hybrid search engine; BM25 probe short-circuit, HyDE query expansion, llm_cache, 900-token AST-aware chunking with tree-sitter (Slices 6–7)

### TurboQuant / Vector Quantization
- [TurboQuant: Online Vector Quantization with Near-optimal Distortion Rate](https://arxiv.org/abs/2504.19874) — ICLR 2026; zero-training compression, ~6× at 95% recall; target for the LanceDB+TurboQuant experiment in Slice 6
- [PolarQuant: Vector Quantization with Polar Transformation](https://openreview.net/forum?id=Igzjw1Pkds) — AISTATS 2026; Stage 1 of TurboQuant (random rotation + scalar quantization)
- [TurboQuant Google Research blog](https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/) — accessible overview of the two-stage design
- [RyanCodrai/turbovec](https://github.com/RyanCodrai/turbovec) — Rust/SIMD TurboQuant index; reference implementation for the scoring kernel to adapt into the LanceDB experiment

---

## Suggested build order

```text
Slice 1: Repo Access & Snapshot Registry ← start here, unblocks everything
Slice 2: Code IR              ← tree-sitter parse, core data model
Slice 3: AST-Aware Search     ← first usable search for agents
  ─── MVP: agents can snapshot a repo and search it ───
Slice 4: Lexical Index        ← performance upgrade (scan → index)
Slice 5: Symbol Graph         ← cross-file navigation (KuzuDB)
Slice 6: Semantic Retrieval   ← fuzzy/conceptual search (LanceDB)
Slice 7: Query Planner        ← unified interface
Slice 8: Impact Analysis      ← change reasoning
Slice 9: LangChain Tools      ← wire everything as @tool functions
  ─── Shipped: integrated codesearch service ───

  [ later, when needed ]
Slice 10: Workspace Sync      ← incremental re-indexing
Slice 11: Secure Sharing      ← multi-tenant index reuse
  ─── CLI / MCP extraction ← natural trigger for 10-11 ───
Slice 12: Agent UX & Eval     ← trust, telemetry, eval harness
```
