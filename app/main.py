from contextlib import asynccontextmanager

from fastapi import FastAPI
from phoenix.otel import register

# Import graphs package to trigger workflow registration
import app.engine.graphs  # noqa: F401
from app.api.v1.router import api_router
from app.logger import logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    register(
        project_name="code-reviewer",
        auto_instrument=True,
    )
    logger.info("Phoenix OTEL tracer registered")
    yield


app = FastAPI(lifespan=lifespan)

# Include API v1 router
app.include_router(api_router, prefix="/api/v1")


@app.get("/")
def read_root():
    return {"message": "Welcome to the Code Reviewer API"}
