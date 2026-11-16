<div align="center">

# obsidian-agent

**A LangGraph research pipeline that turns a topic into a report, atomic Zettel notes, and durable memories — through three sequential LLM agents.**

<a href="https://opensource.org/licenses/Apache-2.0">
  <img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License: Apache 2.0" />
</a>
<br></br>
<i>Researcher → Summarizer → Zettelkasten → Persist</i>
<br></br>
</div>

A single POST kicks off a full research run: the researcher gathers
sources (web search, MCP tools, Monty-backed shell Python), the
summarizer produces a Markdown report, the zettelkasten agent extracts
atomic notes into `notes/`, and the persist node writes a Polars CSV
of sources and a frontmatter-rich memory inside the selected vault, mounted
at `/memory` for later Unix-style archaeology.

See [**ARCHITECTURE.md**](./ARCHITECTURE.md) for the full mental model,
domain types, invariants, and extension points — read it before
proposing design changes.

Plans, implementation tasks and research audits live in the
[development archive](docs/development.md).

## Quick start

Configure workflow authentication and approved vault paths first; see
[workflow access](docs/security-access.md). Empty credentials or allowlists
fail closed. Container vault paths require explicit writable mounts.

uv installs the pinned Cercova `sqlite-vec` release from its explicit public
package index. Supported Linux, macOS and Windows platforms use wheels; Alpine
builds from the source archive with the compiler supplied by the Containerfile.

```bash
# Prerequisites: podman + provider keys + configured workflow access
# Compose also requires an exported, generated POSTGRES_PASSWORD.

just up                                   # app + postgres + phoenix
# or, locally without the stack:
just run                                  # uvicorn with --reload

# Fire a research run
curl -sS -X POST http://localhost:8000/api/v1/workflows/run/research \
  -H "Authorization: Bearer $SECURITY__WORKFLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"topic":"emerging patterns in retrieval-augmented generation","vault":{"type":"local","path":"/path/to/Vault"}}'

# Use a local Obsidian vault as the workspace base
curl -sS -X POST http://localhost:8000/api/v1/workflows/run/research \
  -H "Authorization: Bearer $SECURITY__WORKFLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"topic":"zettelkasten workflows","vault":{"type":"local","path":"/path/to/Vault"}}'

# Use an explicitly approved public GitHub HTTPS vault (not pushed)
curl -sS -X POST http://localhost:8000/api/v1/workflows/run/research \
  -H "Authorization: Bearer $SECURITY__WORKFLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"topic":"zettelkasten workflows","vault":{"type":"git","url":"https://github.com/user/vault.git","ref":"main"}}'
```

Registered workflows: `research` (full pipeline), `researcher`,
`summarizer`, `zettelkasten` (each agent standalone), and `connect`.

### Find connections between existing notes

`connect` proposes up to eight cross-field analogies for human review. Start the
local embedding sidecar with `just embed`, then request an approved test vault:

```sh
curl -sS -X POST http://localhost:8000/api/v1/workflows/run/connect \
  -H "Authorization: Bearer $SECURITY__WORKFLOW_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"topic":"Find useful structural analogies","vault":{"type":"local","path":"/path/to/TestVault"}}'
```

The response's `artifacts.connect` points to `outputs/connect/<run_id>.json`.
The report contains draft `Hypothesis` proposals, exact source quotes, source
paths and SHA-256 hashes, mappings, limitations, and candidate counts. It does
not edit source notes or graph links. Exact quotes establish source presence;
they do not prove that an analogy is correct. Review proposals before using them.

This pilot accepts at most 36 Markdown source notes under `notes/`, each at most
64 KiB. It supplies up to 200 title characters and 1,500 body characters per note
to the configured model, marking shortened sources in the report. The topic may
contain at most 1,500 characters. The model receives those excerpts in one
tool-free judgment call; it can return fewer proposals or none. Empty candidate
pools produce an empty report without a model call. Linked pairs within two hops
of the source-note graph are excluded. Tags do not determine field difference.

## What gets produced

Paths below are **vault-relative**. Every request must provide
`vault.type=local|git`; the layout is written under the selected vault root
(`{vault_root}/outputs/...`, `{vault_root}/notes/...`,
`{vault_root}/.memories/...`).

| Path | Written by | Contents |
|---|---|---|
| `{vault}/outputs/report.md` | persist | Full research report |
| `{vault}/outputs/sources.csv` | persist | Polars-written source table |
| `{vault}/notes/*.md` | persist | Atomic Markdown notes |
| `{vault}/.memories/{slug}-{ts}.md` | persist | Run log with frontmatter; mounted at `/memory` in agent workspaces |
| `{vault}/outputs/connect/<run_id>.json` | connect | Run-owned draft Hypothesis proposals and source evidence |
| `.assets/{owner}/{repo}@{sha}/` | GitHub snapshots | Tarball-extracted repo trees (only when a GH workflow asks for them) |
| `.logs/app.log` | logger | Rotating log (10 MB / 1 week) |

Reports and source CSVs overwrite the previous run. Note IDs can overwrite
prior-run notes; use a dedicated vault or a backup when retaining earlier output.

## Configuration

- `.env` — secrets and runtime knobs. Nested fields use `__`
  (e.g. `GITHUB__APP_ID=123`).
- `app/core/resources/agent_config.yaml` — LLM and per-agent system
  prompts. Loaded as a lower-precedence source behind env vars.
- Key keys: `DATABASE_URL` (enables `AsyncPostgresSaver`; empty falls
  back to in-memory checkpointing), `OPENAI_API_KEY`,
  `JINA_API_KEY`,
  `GITHUB__APP_ID`, `GITHUB__PRIVATE_KEY`, `GITHUB__INSTALLATION_ID`.

## Local development

```bash
uv sync                           # install deps (Python 3.13+)
just check                        # ruff, pyright, import boundaries, pytest (§11.2)
just fmt                          # ruff format + lint --fix
just phoenix                      # OTEL UI at http://localhost:6006
just db-up                        # local postgres for checkpointing
```

Common `just` targets: `check`, `review`, `run`, `up`, `up-logs`, `down`,
`logs`, `fmt`, `clean`, `phoenix`, `db-up`, `agents`.

## Agent scaffolding

`setup-agents.sh` provisions `.agents/` plus per-IDE dotdirs (`.claude`,
`.cursor`, `.codex`, …) via symlinks, pulling shared commands, hooks,
and skills from
[`cercova-studios/10x-swe`](https://github.com/cercova-studios/10x-swe).
Full usage: [docs/setup-agents.md](./docs/setup-agents.md).

```bash
just agents                       # interactive
./setup-agents.sh --list          # show registry without side effects
PLUGIN_VERSION=v2.0 ./setup-agents.sh 1  # pin a tag and pick Claude only
```

## Copilot pre-commit autofix hook

Husky runs a Bun-based hook (`.husky/pre-commit.ts`) that calls the
`@github/copilot-sdk` to fix pre-commit failures in a bounded retry
loop. It only kicks in when `pre-commit run` fails and no in-tree
auto-fixes were produced.

Start a headless Copilot CLI server, export the token, and commit:

```bash
export COPILOT_TOKEN=ghp_your_token
export COPILOT_GITHUB_TOKEN="$COPILOT_TOKEN"
copilot --headless --port 4321
git commit -m "…"
```

Hook env vars:

| Variable | Default | Purpose |
|---|---|---|
| `COPILOT_CLI_URL` | SDK default (`localhost:4321`) | Headless server URL |
| `COPILOT_MAX_ITER` | `3` | Maximum fix-and-retry passes |
| `ALL_FILES` | *(unset)* | `1` runs `pre-commit --all-files` |

Model: `gpt-5.4-mini` (hard-coded).

## License

Licensed under [Apache 2.0](LICENSE).
