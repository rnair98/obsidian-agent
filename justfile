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

# Format and lint the codebase
fmt:
    uv run ruff format
    uv run ruff check --fix --unsafe-fixes .

# Start Arize Phoenix for tracing
phoenix:
    podman run --rm -it -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest

run:
    uv run uvicorn app.main:app --reload --port 8000

# Spin up a local Postgres test database
db-up:
    podman run --name test-db -e POSTGRES_PASSWORD=password -p 5432:5432 -d postgres:alpine

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
