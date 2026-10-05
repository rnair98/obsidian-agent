set shell := ["bash", "-c"]    

# List available recipes
default:
    @just --list

# Setup agent environments
agents:
    ./setup-agents.sh

# Remove Python cache files & logs
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete
    find . -type d -name ".ruff_cache" -exec rm -rf {} +
    find . -type d -name ".logs" -exec rm -rf {} +

# Outer harness. ARCHITECTURE.md §11.2
check:
    uv run ruff check app tests .cursor/hooks
    uv run pyright
    uv run lint-imports
    uv run pytest

# Hand the diff to a fresh reviewer. ARCHITECTURE.md §11.3
review:
    @echo "Start a new agent. Its only instruction is .cursor/skills/adversarial-qa/SKILL.md"
    @echo "It reads the diff itself. Do not paste a summary of intent."
    git status --short
    git diff --stat HEAD

# Format and lint the codebase
fmt:
    uv run ruff format
    uv run ruff check --fix --unsafe-fixes .

typecheck:
    uv run pyright

# Generate openapi.json from the FastAPI app
openapi:
    uv run python -c "import json; from app.main import app; print(json.dumps(app.openapi(), indent=2))" > openapi.json
    @echo "wrote openapi.json"

# Start Arize Phoenix for tracing
phoenix:
    podman run --rm -it -p 127.0.0.1:6006:6006 -p 127.0.0.1:4317:4317 arizephoenix/phoenix:latest

run:
    uv run uvicorn app.main:app --reload --port 8000

# Spin up a local Postgres test database
db-up:
    test -n "${POSTGRES_PASSWORD:-}"
    podman run --name test-db -e POSTGRES_PASSWORD -p 127.0.0.1:5432:5432 -d postgres:alpine

# Spin up the entire stack (app, phoenix, db)
up:
    podman compose up -d

# Spin up the entire stack and follow logs
up-logs:
    podman compose up -d && podman compose logs -f

# Spin down the entire stack
down:
    podman compose down

# Show logs for the services
logs:
    podman compose logs -f
