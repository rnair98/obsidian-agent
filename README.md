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
atomic notes into `.vault/`, and the persist node writes a Polars CSV
of sources and a frontmatter-rich memory inside the selected vault, mounted
at `/memory` for later Unix-style archaeology.

See [**ARCHITECTURE.md**](./ARCHITECTURE.md) for the full mental model,
domain types, invariants, and extension points — read it before
proposing design changes.

## Quick start

```bash
# Prerequisites: podman (or docker) + OPENAI_API_KEY in your environment

just up                                   # app + postgres + phoenix
# or, locally without the stack:
just run                                  # uvicorn with --reload

# Fire a research run
curl -sS -X POST http://localhost:8000/api/v1/workflows/run/research \
  -H "Content-Type: application/json" \
  -d '{"topic": "emerging patterns in retrieval-augmented generation"}'

# Use a local Obsidian vault as the workspace base
curl -sS -X POST http://localhost:8000/api/v1/workflows/run/research \
  -H "Content-Type: application/json" \
  -d '{"topic":"zettelkasten workflows","vault":{"type":"local","path":"/path/to/Vault"}}'

# Use a remote Git vault as the workspace base (cloned locally; not pushed)
curl -sS -X POST http://localhost:8000/api/v1/workflows/run/research \
  -H "Content-Type: application/json" \
  -d '{"topic":"zettelkasten workflows","vault":{"type":"git","url":"https://github.com/user/vault.git","ref":"main"}}'
```

Registered workflows: `research` (full pipeline), `researcher`,
`summarizer`, `zettelkasten` (each agent standalone).

## What gets produced

Paths below are **vault-relative**. When the request omits a vault the
managed `.vault/` directory is used; when `vault.type=local|git` is supplied
the same layout is written under the selected vault root
(`{vault_root}/outputs/...`, `{vault_root}/notes/...`,
`{vault_root}/.memories/...`).

| Path | Written by | Contents |
|---|---|---|
| `{vault}/outputs/report.md` | persist | Full research report |
| `{vault}/outputs/sources.csv` | persist | Polars-written source table |
| `{vault}/notes/*.md` | persist | Atomic Markdown notes |
| `{vault}/.memories/{slug}-{ts}.md` | persist | Run log with frontmatter; mounted at `/memory` in agent workspaces |
| `.assets/{owner}/{repo}@{sha}/` | GitHub snapshots | Tarball-extracted repo trees (only when a GH workflow asks for them) |
| `.logs/app.log` | logger | Rotating log (10 MB / 1 week) |

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
just fmt                          # ruff format + lint --fix
uv run pytest                     # full test suite
just phoenix                      # OTEL UI at http://localhost:6006
just db-up                        # local postgres for checkpointing
```

Common `just` targets: `run`, `up`, `up-logs`, `down`, `logs`, `fmt`,
`clean`, `phoenix`, `db-up`, `agents`.

## Agent scaffolding

`setup-agents.sh` provisions `.agents/` plus per-IDE dotdirs (`.claude`,
`.cursor`, `.codex`, …) via symlinks, pulling shared commands, hooks,
and skills from
[`cercova-studios/terminal-agent-plugins`](https://github.com/cercova-studios/terminal-agent-plugins).
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

No license file has been added yet — treat the repository as
all-rights-reserved until one lands.
