from __future__ import annotations

from time import monotonic

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

log = structlog.get_logger(__name__)

_SLOW_QUERY_MS = 100


class Base(DeclarativeBase):
    pass


# echo=False always — never log SQL text or bind parameters (may contain PII).
# Slow queries are surfaced via the event listeners below.
engine = create_async_engine(
    settings.database_url,
    pool_size=10,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine.sync_engine, "before_cursor_execute")
def _before_execute(conn, cursor, statement, parameters, context, executemany):
    conn.info["_query_start"] = monotonic()


@event.listens_for(engine.sync_engine, "after_cursor_execute")
def _after_execute(conn, cursor, statement, parameters, context, executemany):
    start = conn.info.pop("_query_start", None)
    if start is None:
        return
    elapsed_ms = int((monotonic() - start) * 1000)
    if elapsed_ms >= _SLOW_QUERY_MS:
        # Log only elapsed time and statement kind — never params (PII risk).
        words = statement.strip().split()
        stmt_kind = words[0].upper() if words else "UNKNOWN"
        log.warning("db.slow_query", elapsed_ms=elapsed_ms, stmt_kind=stmt_kind)
