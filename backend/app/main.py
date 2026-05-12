from contextlib import asynccontextmanager
from urllib.parse import urlparse

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.logging import setup_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    log.info("app.startup", env=settings.app_env, provider=settings.default_llm_provider)
    yield
    log.info("app.shutdown")


app = FastAPI(
    title="Coach Agent API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env != "production" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)

if settings.app_env == "production":
    # Extract hostnames from CORS origins; always allow localhost for Docker health checks
    _hosts = {urlparse(o).hostname for o in settings.allowed_origins if o != "*" and o}
    _hosts |= {"localhost", "127.0.0.1"}
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(_hosts))


app.include_router(v1_router, prefix="/api/v1")


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "env": settings.app_env, "version": "0.1.0"}
