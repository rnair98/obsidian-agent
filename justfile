set shell := ["bash", "-c"]    

# List available recipes
default:
    @just --list

# Setup agent environments
agents:
    ./setup-agents.sh

# Remove Python cache files
clean:
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type f -name "*.pyc" -delete

# Format and lint the codebase
fmt:
    uv run ruff format
    uv run ruff check --fix --unsafe-fixes .

# Start Arize Phoenix for tracing
phoenix:
    docker run --rm -it -p 6006:6006 -p 4317:4317 arizephoenix/phoenix:latest

run:
    uv run uvicorn app.main:app --reload --port 8000
