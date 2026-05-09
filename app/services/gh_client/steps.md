# Implementation Steps

> **Current state**: Slice 1 is ~70% complete. `shallow_clone()` and the
> `SnapshotResult` TypedDict exist in `gh_client/`. No `codesearch/` service
> exists. No tree-sitter, kuzu, lancedb, or sentence-transformers dependencies.
>
> **Goal**: Slices 1–9 shipped as an integrated LangChain codesearch service.

---

## Step 1 — Finish Slice 1: Snapshot registry

**Files to touch**: `app/services/gh_client/types.py`, `app/services/gh_client/repo.py`

### 1a. Promote `SnapshotResult` to Pydantic

`types.py` currently defines `SnapshotResult` as a `TypedDict`. Replace it with
a `pydantic.BaseModel` so downstream code gets validation, serialization, and
`.model_dump()` for free.

```python
# types.py
from pydantic import BaseModel

class SnapshotResult(BaseModel):
    repo_name: str
    commit_sha: str
    requested_ref: str
    path: Path
    created_at: datetime
    skipped: bool
```

`repo.py` already passes keyword arguments to `SnapshotResult(...)` so no call
sites need to change — Pydantic accepts the same kwargs.

### 1b. Add `list_snapshots` and `delete_snapshot`

Add two methods to `GitHubRepositoryService` (or as module-level functions in a
new `snapshot.py` — either works, module-level is simpler to test):

```python
def list_snapshots(base_path: Path, repo_name: str | None = None) -> list[SnapshotResult]:
    """Enumerate snapshot directories under base_path/owner/repo@sha/.
    Optionally filter to a single repo_name (owner/repo)."""

def delete_snapshot(base_path: Path, repo_name: str, commit_sha: str) -> None:
    """Delete <base_path>/<owner>/<repo>@<sha>/ and its contents."""
```

`list_snapshots` should reconstruct `SnapshotResult` from the directory name
(parse `owner/repo@sha` from the path). Use `Path.stat().st_mtime` for the
portable filesystem timestamp; `st_ctime` is metadata-change time on Unix-like
systems, not creation time.

### Done when

- `list_snapshots(base_path)` returns all existing snapshots without hitting GitHub.
- `delete_snapshot(base_path, "octocat/Hello-World", sha)` removes the directory.
- `SnapshotResult` is a Pydantic model.

### Commit message

```
refactor(snapshot): promote SnapshotResult to Pydantic and add registry helpers

Add list_snapshots() and delete_snapshot() so callers can enumerate and remove
local snapshots without hitting GitHub. Promote SnapshotResult from TypedDict
to Pydantic BaseModel for validation and .model_dump() support.
```

---

## Step 2 — Slice 2: Code IR (tree-sitter parse)

**New dependency**: `uv add "tree-sitter>=0.23" tree-sitter-language-pack`

**New directory**: `app/services/codesearch/`

**Files to create**:

```
app/services/codesearch/
├── __init__.py
├── models.py       # FileIR, Symbol, Scope, Import — Pydantic
├── languages.py    # extension → tree-sitter grammar mapping
└── parser.py       # parse_file, parse_snapshot
```

### 2a. `models.py`

```python
class Symbol(BaseModel):
    name: str
    kind: str          # "function" | "class" | "method" | "variable"
    file: str
    start_line: int
    end_line: int

class Scope(BaseModel):
    name: str
    kind: str
    start_line: int
    end_line: int

class Import(BaseModel):
    module: str
    names: list[str]
    line: int

class FileIR(BaseModel):
    path: str
    language: str
    symbols: list[Symbol]
    scopes: list[Scope]
    imports: list[Import]
    lines: list[str]
```

### 2b. `languages.py`

Map file extensions to tree-sitter language names. Start with:
`{".py": "python", ".ts": "typescript", ".js": "javascript", ".go": "go",
".rs": "rust", ".java": "java"}`. Return `None` for unknown extensions
so `parse_file` can skip them gracefully.

### 2c. `parser.py`

```python
def parse_file(path: Path) -> FileIR | None:
    """Parse a single source file. Returns None for unsupported/binary files."""

def parse_snapshot(snapshot_path: Path) -> list[FileIR]:
    """Walk snapshot tree, skip vendor/binary/generated, parse all supported files."""
```

`parse_file` should:
1. Detect language via `languages.py`.
2. Load grammar from `tree-sitter-language-pack`.
3. Walk the CST to extract `Symbol`, `Scope`, and `Import` nodes.
4. Store raw lines for context retrieval in later slices.

Skip heuristics for `parse_snapshot`: paths containing `vendor/`, `node_modules/`,
`.min.js`, `_pb2.py`, files > 500KB, binary files (check `\x00` in first 8KB).

### Done when

- `parse_file("example.py")` returns a `FileIR` with correct function/class
  symbols and line ranges.
- `parse_snapshot(snapshot_path)` runs without errors on a multi-language repo
  and returns one `FileIR` per parseable file.

### Commit message

```
feat(codesearch): add tree-sitter IR parser with FileIR, Symbol, Scope models

Parse Python, TypeScript, JavaScript, Go, Rust, and Java source files into a
typed IR (FileIR, Symbol, Scope, Import). parse_snapshot walks a snapshot tree,
skips vendor/binary/generated files, and returns one FileIR per parseable file.
```

---

## Step 3 — Slice 3: AST-Aware Search

**Files to create**:

```
app/services/codesearch/
└── search.py       # search_code, search_symbols, get_context
```

Add to `models.py`:

```python
class SearchResult(BaseModel):
    file: str
    line: int
    match: str
    enclosing_symbol: Symbol | None
    scope_chain: list[str]
    preview: str           # a few lines of context around the match

class ContextResult(BaseModel):
    file: str
    start_line: int
    end_line: int
    lines: list[str]
    enclosing_symbol: Symbol | None
    scope_chain: list[str]
```

### `search.py`

```python
def search_code(
    snapshot_path: Path,
    pattern: str,
    language: str | None = None,
    path_glob: str | None = None,
    symbol_kind: str | None = None,
) -> list[SearchResult]:
    """Regex/literal search over parsed IR with AST context."""

def search_symbols(
    snapshot_path: Path,
    name: str,
    kind: str | None = None,
) -> list[Symbol]:
    """Lookup symbols by name/kind across the snapshot."""

def get_context(
    snapshot_path: Path,
    file: str,
    line: int,
    radius: int = 5,
) -> ContextResult:
    """Return AST-aware context: full enclosing scope, not just ±N lines."""
```

For `get_context`, use the `FileIR.scopes` list to find the tightest enclosing
scope for the target line and return its full range — not just `line ± radius`.

### Done when

- `search_code(snapshot, "authenticate")` returns matches with enclosing
  symbol names.
- `get_context(snapshot, "auth.py", 42)` returns the enclosing function body,
  not a fixed window.

### Commit message

```
feat(codesearch): add AST-aware search, symbol lookup, and scope-aware context

search_code returns matches with enclosing symbol and scope chain. search_symbols
finds definitions by name and kind. get_context expands to the full enclosing
scope rather than a fixed line window.
```

---

## Step 4 — Slice 4: Lexical Index

**Files to create**:

```
app/services/codesearch/
└── index.py        # build_index, query_index, rebuild_index, index_exists
```

The index lives at `<snapshot_path>/.codesearch.db`.

### Schema (inline in `index.py`)

```sql
-- FTS5 full-text index
CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(
    chunk_id UNINDEXED,
    file UNINDEXED,
    line UNINDEXED,
    language UNINDEXED,
    symbol_kind UNINDEXED,
    content,
    tokenize='porter unicode61'
);

-- Trigram table for substring queries
CREATE VIRTUAL TABLE IF NOT EXISTS code_trigram USING fts5(
    chunk_id UNINDEXED,
    file UNINDEXED,
    line UNINDEXED,
    content,
    tokenize='trigram'
);

-- LLM output cache (used by Query Planner, Slice 7)
CREATE TABLE IF NOT EXISTS llm_cache (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    created_at REAL NOT NULL
);
```

### `index.py`

```python
def build_index(snapshot_path: Path) -> Path:
    """Tokenize all FileIR lines, populate FTS5 and trigram tables.
    Returns path to .codesearch.db."""

def query_index(
    db_path: Path,
    query: str,
    mode: Literal["fts", "substring"] = "fts",
    language: str | None = None,
    path_glob: str | None = None,
    symbol_kind: str | None = None,
    top_k: int = 50,
) -> list[SearchResult]:
    """FTS5 MATCH (fts mode) or trigram scan (substring mode) with filter pushdown."""

def index_exists(snapshot_path: Path) -> bool: ...
def rebuild_index(snapshot_path: Path) -> Path: ...
def drop_index(snapshot_path: Path) -> None: ...
```

**Impact-ordered retrieval note**: FTS5's BM25 scoring (`rank`) is already
impact-ordered; use `ORDER BY rank` in queries. The trigram table uses LIKE
for substring matching and does not benefit from BM25 — keep it separate.

### Done when

- `build_index(snapshot)` creates `.codesearch.db` with populated tables.
- `query_index(db, "authenticate")` returns results faster than `search_code`
  scan on the same snapshot.
- `query_index(db, "erAuth", mode="substring")` finds `UserAuthHandler`.

### Commit message

```
feat(codesearch): add SQLite FTS5 + trigram lexical index with llm_cache table

build_index tokenizes all FileIR lines into a co-located .codesearch.db.
query_index supports BM25 full-text (fts mode) and arbitrary substring matching
(trigram mode) with language/path/symbol-kind filter pushdown. Includes
llm_cache table for caching query expansion outputs in later slices.
```

---

## Step 5 — Slice 5: Symbol Graph

**New dependency**: `uv add kuzu`

**Files to create**:

```
app/services/codesearch/
└── graph.py        # build_symbol_graph, find_references, find_dependents, get_call_graph
```

Add to `models.py`:

```python
class Reference(BaseModel):
    file: str
    line: int
    symbol: Symbol
    kind: str   # "import" | "call" | "use"

class Dependent(BaseModel):
    file: str
    symbol: Symbol | None
    via: str    # the import/call path

class CallGraph(BaseModel):
    root: Symbol
    edges: list[tuple[str, str]]   # (caller_id, callee_id)
    nodes: list[Symbol]
```

### `graph.py`

```python
def build_symbol_graph(snapshot_path: Path) -> Path:
    """Walk all FileIRs, build KuzuDB graph at <snapshot_path>/.graph/.
    Schema: Symbol nodes, IMPORTS/CALLS/REFERENCES/DEFINES edges."""

def find_references(graph_path: Path, symbol_name: str) -> list[Reference]:
    """All usages of a symbol across files. Runs a Cypher MATCH query."""

def find_dependents(graph_path: Path, file_or_symbol: str) -> list[Dependent]:
    """Reverse dependency traversal."""

def get_call_graph(graph_path: Path, function_name: str) -> CallGraph:
    """BFS/DFS from a function node via CALLS edges."""
```

**KuzuDB schema** (run at graph creation time):

```cypher
CREATE NODE TABLE Symbol(id STRING, name STRING, kind STRING,
    file STRING, start_line INT64, end_line INT64, repo STRING, PRIMARY KEY(id))
CREATE REL TABLE IMPORTS(FROM Symbol TO Symbol)
CREATE REL TABLE CALLS(FROM Symbol TO Symbol)
CREATE REL TABLE REFERENCES(FROM Symbol TO Symbol)
CREATE REL TABLE DEFINES(FROM Symbol TO Symbol)
```

### Done when

- `find_references(graph, "UserService")` returns all files/lines that use it.
- `find_dependents(graph, "auth.py")` returns files that import from it.
- Graph persists between process restarts (no rebuild needed).

### Commit message

```
feat(codesearch): add KuzuDB symbol graph with cross-file reference traversal

build_symbol_graph persists a typed property graph (Symbol nodes, IMPORTS/
CALLS/REFERENCES/DEFINES edges) at <snapshot>/.graph/ using KuzuDB. Graph
survives process restarts. find_references and find_dependents run Cypher
queries; get_call_graph BFS-traverses CALLS edges from a root function.
```

---

## Step 6 — Slice 6: Semantic Retrieval

**New dependencies**: `uv add sentence-transformers lancedb`

**Files to create**:

```
app/services/codesearch/
└── embeddings.py   # build_embeddings, semantic_search
```

Add to `models.py`:

```python
class SemanticResult(BaseModel):
    chunk_id: str
    file: str
    start_line: int
    end_line: int
    symbol_name: str | None
    language: str
    content: str
    score: float
```

### `embeddings.py`

```python
def build_embeddings(snapshot_path: Path, model_name: str = "nomic-ai/nomic-embed-code") -> Path:
    """
    AST-aware chunking + embed + store in LanceDB at <snapshot_path>/.embeddings/.

    Chunking rules:
    - Target 900 tokens per chunk, 15% overlap.
    - Chunk at function/class boundaries from FileIR.
    - For large functions exceeding the target: split at highest-scoring
      AST sub-boundary (score: function_def > block > expression > statement).
    - Dedup by SHA-256 of content — identical chunks stored once.

    Table schema: chunk_id, file, start_line, end_line, symbol_name,
                  language, repo, content, vector.
    """

def semantic_search(
    embeddings_path: Path,
    query: str,
    top_k: int = 10,
    language: str | None = None,
    path_glob: str | None = None,
) -> list[SemanticResult]:
    """Single LanceDB query: SQL WHERE filter + vector ANN scan."""
```

**TurboQuant experiment** (optional, attempt after basic LanceDB path works):
Pre-compress embeddings with TurboQuant (random rotation → Lloyd-Max scalar
quantization → store codes + norm as a binary column alongside the vector).
At query time, fetch binary codes and score via asymmetric dot product using
the `turbovec` Rust kernel. Fallback: use LanceDB's default IVF-PQ index if
the custom scoring integration is too rough.

### Done when

- `semantic_search(path, "user authentication flow")` returns auth-related
  functions that don't literally contain "authentication".
- New chunks can be inserted without retraining — LanceDB supports online inserts.

### Commit message

```
feat(codesearch): add LanceDB semantic index with AST-aware chunking

build_embeddings chunks at function/class boundaries (900-token target, 15%
overlap, AST sub-boundary scoring for large functions), embeds with
sentence-transformers, and stores vectors + metadata in a single LanceDB table
at <snapshot>/.embeddings/. semantic_search applies SQL WHERE filters before
the ANN scan. Content-hash dedup prevents duplicate chunks.
```

---

## Step 7 — Slice 7: Query Planner & Fusion

**Files to create**:

```
app/services/codesearch/
├── planner.py      # plan_query, execute_plan
└── fusion.py       # rrf_merge, rerank, hyde_expand, llm_cache helpers
```

Add to `models.py`:

```python
class QueryPlan(BaseModel):
    query: str
    query_type: Literal["exact", "fuzzy", "hybrid"]
    intent: str | None
    use_hyde: bool
    legs: list[Literal["lexical", "semantic"]]
    filters: dict[str, str]

class FusedResult(BaseModel):
    file: str
    line: int
    preview: str
    score: float
    sources: list[str]   # which legs contributed: ["lexical", "semantic"]
    confidence: float
```

### `planner.py`

```python
def plan_query(
    query: str,
    scope: dict | None = None,
    intent: str | None = None,
) -> QueryPlan:
    """
    Classify query type and build execution plan.

    exact  → lexical only (identifier patterns, file paths, symbol names)
    fuzzy  → semantic only (conceptual queries) — use_hyde=True by default
    hybrid → both + RRF

    intent="snippet" forces lexical even on fuzzy queries.
    """

def execute_plan(plan: QueryPlan, snapshot_path: Path) -> list[FusedResult]:
    """
    1. Run lexical leg if in plan.legs → get BM25 results.
    2. BM25 confidence gate: if lexical returns ≥k results above threshold
       AND intent is None → skip semantic leg.
    3. Run semantic leg if not gated out:
       a. If plan.use_hyde: generate hypothetical code snippet (via llm_cache),
          embed the snippet instead of raw query.
       b. Run LanceDB semantic_search.
    4. Merge via RRF (first-leg results carry 2× weight).
    5. Optional reranker pass on top-k.
    """
```

### `fusion.py`

```python
def rrf_merge(
    result_lists: list[list[Any]],
    weights: list[float] | None = None,   # first list gets 2× by default
    k: int = 60,
) -> list[FusedResult]:
    """Standard RRF: score = sum(weight / (k + rank)). Merge and deduplicate."""

def hyde_expand(query: str, db_path: Path, llm) -> str:
    """Generate a hypothetical code snippet for query. Check llm_cache first."""

def cache_get(db_path: Path, key: str) -> str | None: ...
def cache_set(db_path: Path, key: str, value: str) -> None: ...
```

### Done when

- `execute_plan(plan_query("how does auth work?", scope={"repo": "org/app"}), snapshot)`
  returns ranked results from multiple legs with source tags.
- A repeated query hits `llm_cache` instead of calling the LLM again.
- BM25 gate skips semantic search for an exact identifier query.

### Commit message

```
feat(codesearch): add query planner with BM25 confidence gate, HyDE, and RRF fusion

plan_query classifies queries as exact/fuzzy/hybrid and accepts an intent
parameter for routing overrides. execute_plan short-circuits the semantic leg
when BM25 returns a strong signal. Fuzzy queries use HyDE (hypothetical code
snippet embedding) cached in llm_cache. RRF merge weights the first leg 2×;
optional reranker pass applies position-aware blending.
```

---

## Step 8 — Slice 8: Impact Analysis

**Files to create**:

```
app/services/codesearch/
└── impact.py       # analyze_impact, validate_commit
```

Add to `models.py`:

```python
class ImpactReport(BaseModel):
    changed_files: list[str]
    affected_files: list[str]
    affected_tests: list[str]
    confidence: float
    graph_coverage: float   # fraction of symbols with resolved edges

class CommitValidation(BaseModel):
    added: list[str]
    removed: list[str]
    modified: list[str]
    impact: ImpactReport
```

### `impact.py`

```python
def analyze_impact(graph_path: Path, changed_files: list[str]) -> ImpactReport:
    """
    For each changed file:
    1. Find its exported symbols via KuzuDB.
    2. BFS REFERENCES/CALLS edges outward to find all consumers.
    3. Identify test files (files matching *test*, *spec* patterns) in the
       affected set.
    Confidence = fraction of edges that resolved (not approximated).
    """

def validate_commit(
    snapshot_a: Path,
    snapshot_b: Path,
) -> CommitValidation:
    """Diff two snapshots by path+content hash, compute impact on the delta."""
```

### Done when

- `analyze_impact(graph, ["auth.py"])` returns a ranked list of affected files
  and test files with confidence scores.

### Commit message

```
feat(codesearch): add impact analysis and two-snapshot commit validation

analyze_impact BFS-traverses REFERENCES/CALLS edges from changed files to find
all consumers and surfaces test files separately. validate_commit diffs two
snapshots by content hash and runs impact analysis on the delta. Both return
confidence scores based on graph edge coverage.
```

---

## Step 9 — Slice 9: LangChain Tool Surface

**Files to create**:

```
app/engine/tools/codesearch.py   # @tool wrappers only — no service imports at module level
```

### Tools to implement

Each tool is a thin `@tool`-decorated function that:
1. Calls `get_github_client()` to resolve auth (already exists).
2. Resolves the snapshot path via `list_snapshots()`.
3. **Lazy-builds missing indexes on first call**: if `.codesearch.db` /
   `.graph/` / `.embeddings/` don't exist, call the appropriate `build_*`
   function before querying.
4. Delegates to the pure service function.

```python
@tool("search_code")
def search_code_tool(query: str, repo: str, language: str | None = None) -> list[dict]: ...

@tool("search_symbols")
def search_symbols_tool(name: str, repo: str, kind: str | None = None) -> list[dict]: ...

@tool("get_context")
def get_context_tool(repo: str, file: str, line: int) -> dict: ...

@tool("find_references")
def find_references_tool(symbol: str, repo: str) -> list[dict]: ...

@tool("find_dependents")
def find_dependents_tool(file_or_symbol: str, repo: str) -> list[dict]: ...

@tool("analyze_impact")
def analyze_impact_tool(changed_files: list[str], repo: str) -> dict: ...

@tool("cypher")
def cypher_tool(query: str, repo: str) -> list[dict]:
    """Run a raw Cypher query against the symbol graph."""

@tool("list_snapshots")
def list_snapshots_tool(repo: str | None = None) -> list[dict]: ...
```

### Key constraint

`app/services/codesearch/` must have zero LangChain imports. The `@tool`
wrappers in `codesearch.py` are the only place LangChain is mentioned.
This is the extraction seam for future CLI/MCP work.

### Done when

- The Researcher agent can call `search_code("authenticate", repo="org/app")`
  from a LangGraph node and receive structured results without any REST calls.
- Calling a tool on a fresh snapshot auto-builds all missing indexes.
- All tools are registered in `app/engine/tools/__init__.py`.

### Commit message

```
feat(tools): expose codesearch service as LangChain tools with lazy indexing

Add search_code, search_symbols, get_context, find_references, find_dependents,
analyze_impact, cypher, and list_snapshots as LangGraph @tool wrappers. Each
tool lazy-builds missing indexes on first call. Service layer has no LangChain
imports — wrappers are the only extraction seam for future CLI/MCP work.
```

---

## Dependency additions (all steps)

Run these once after completing the relevant slice:

```bash
# Step 2
uv add "tree-sitter>=0.23" tree-sitter-language-pack

# Step 5
uv add kuzu

# Step 6
uv add sentence-transformers lancedb
```

---

## File layout at completion

```
app/
├── services/
│   ├── gh_client/
│   │   ├── auth.py        (exists)
│   │   ├── repo.py        (exists — add list_snapshots, delete_snapshot)
│   │   └── types.py       (exists — promote to Pydantic)
│   └── codesearch/        (NEW — Steps 2–8)
│       ├── __init__.py
│       ├── models.py      # all Pydantic models
│       ├── languages.py   # extension → grammar map
│       ├── parser.py      # parse_file, parse_snapshot
│       ├── search.py      # search_code, search_symbols, get_context
│       ├── index.py       # FTS5 + trigram + llm_cache
│       ├── graph.py       # KuzuDB symbol graph
│       ├── embeddings.py  # LanceDB + sentence-transformers
│       ├── planner.py     # plan_query, execute_plan
│       ├── fusion.py      # rrf_merge, hyde_expand, cache helpers
│       └── impact.py      # analyze_impact, validate_commit
└── engine/
    └── tools/
        ├── github.py      (exists — get_repo_tree)
        └── codesearch.py  (NEW — Step 9, @tool wrappers)
```
