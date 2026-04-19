# setup-agents.sh — Usage

Bootstraps per-agent scaffolding (`.agents/` plus per-IDE dotdirs) by
cloning a pinned version of
[`cercova-studios/terminal-agent-plugins`](https://github.com/cercova-studios/terminal-agent-plugins)
and wiring its `commands/`, `hooks/`, and `skills/` into each selected
agent's directory via symlinks.

## Run it

```bash
# Interactive picker
./setup-agents.sh

# Non-interactive: choose by registry number (Claude=1, Cursor=2, Codex=3,
# Droid=4, Opencode=5, Copilot=6)
./setup-agents.sh 1,2,6

# Show available agents without making changes
./setup-agents.sh --list

# Pin a specific plugin version (branch, tag, or commit SHA)
PLUGIN_VERSION=v2.0 ./setup-agents.sh 1
```

The script is safe to re-run. It uses `rsync --update` so local
customizations in `.agents/` are preserved.

## What it produces

```text
.agents/
├── .mcp.json            # shared MCP config (empty {} if upstream ships none)
├── .src/                # shallow clone of terminal-agent-plugins
├── commands/            # copied from plugins/10x-swe/agents
├── hooks/               # copied from plugins/10x-swe/hooks
├── rules/               # reserved
└── skills/              # copied from plugins/10x-swe/skills
AGENTS.md                # synced from upstream (created if absent)
.claude/   .cursor/ …    # per-agent dotdirs, symlinked to .agents/*
```

For Claude specifically, the script also enables a preset bundle of
plugins in `.claude/settings.json` (`code-review`, `context7`,
`frontend-design`, `pr-review-toolkit`, `explanatory-output-style`,
`code-simplifier`, and the `10x-swe` plugin itself).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PLUGIN_VERSION` | `main` | Git ref to check out (branch, tag, or SHA) |

## Verifying

```bash
./setup-agents.sh --list          # registry contents, no side effects
ls -la .agents/                   # confirm subdirs populated
readlink .claude/commands         # symlink into .agents/commands
```

## Re-syncing after plugin upstream updates

Re-running the script fetches the pinned `PLUGIN_VERSION` and
`git reset --hard FETCH_HEAD`s the cached clone at `.agents/.src/`,
then reapplies the `rsync --update` merge. Use this when upstream
`terminal-agent-plugins` publishes new commands or skills.
