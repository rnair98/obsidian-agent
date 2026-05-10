from contextlib import asynccontextmanager

from fastapi import FastAPI

# Import graphs package to trigger workflow registration
import app.engine.graphs  # noqa: F401
from app.api.v1.router import api_router
from app.core.logger import logger
from app.core.settings import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.PHOENIX_ENABLED:
        from phoenix.otel import register

        register(project_name="obsidian-agent", auto_instrument=True)
        logger.info("Phoenix OTEL tracer registered")
    else:
        logger.info("Phoenix OTEL tracer disabled (PHOENIX_ENABLED=false)")
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def read_root():
    return {"message": "Welcome to the obsidian-agent API"}
