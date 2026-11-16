FROM ghcr.io/astral-sh/uv:alpine


# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
    && useradd --system --gid 999 --uid 999 --create-home nonroot

WORKDIR /app

RUN apk add --no-cache gcc musl-dev

COPY --from=sqlite-vec pyproject.toml setup.py MANIFEST.in VERSION LICENSE-MIT LICENSE-APACHE /sqlite-vec/
COPY --from=sqlite-vec bindings/python/__init__.py bindings/python/extra_init.py bindings/python/README.md /sqlite-vec/bindings/python/
COPY --from=sqlite-vec bindings/rust/sqlite-vec.c bindings/rust/sqlite-vec.h bindings/rust/sqlite3.h bindings/rust/sqlite3ext.h /sqlite-vec/bindings/rust/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_NO_PROGRESS=1 \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY . /app

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

USER nonroot

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--reload", "--port", "8000"]