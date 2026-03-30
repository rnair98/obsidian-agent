# obsidian-agent

FastAPI application scaffold.

## Copilot pre-commit autofix hook

The Husky pre-commit hook uses `@github/copilot-sdk` against a headless Copilot CLI server.

Set a non-interactive token and start the server before committing:

```bash
export COPILOT_TOKEN=ghp_your_token
export COPILOT_GITHUB_TOKEN="$COPILOT_TOKEN"
copilot --headless --port 4321
```

Optional hook settings:

- `COPILOT_CLI_URL` (default: `localhost:4321`)
- `COPILOT_MAX_ITER` (default: `3`)
- `ALL_FILES=1` to run `pre-commit --all-files`

The hook always uses model `gpt-5.4-mini`.

## Run locally

```bash
uvicorn app.main:app --reload
```
