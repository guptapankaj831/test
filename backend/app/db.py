"""Read-only MySQL engine — shared singleton with a per-connection statement timeout."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from app.config import settings

logger = logging.getLogger(__name__)


def _build_url() -> str:
    # URL-quote in case the password contains `@`/`:`/`?`/`#`.
    user = quote_plus(settings.mysql_user)
    password = quote_plus(settings.mysql_password)
    return (
        f"mysql+pymysql://{user}:{password}"
        f"@{settings.mysql_host}:{settings.mysql_port}/{settings.mysql_db}"
        f"?charset=utf8mb4"
    )


def _create_engine() -> Engine:
    eng = create_engine(
        _build_url(),
        # Drop dead connections instead of failing mid-query.
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        future=True,
    )

    # Server-side SELECT timeout; Python-side timeouts don't kill the query on MySQL.
    @event.listens_for(eng, "connect")
    def _set_statement_timeout(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(
                f"SET SESSION MAX_EXECUTION_TIME = {int(settings.statement_timeout_ms)}"
            )
        finally:
            cursor.close()

    logger.info(
        "db engine ready: user=%s host=%s:%s db=%s timeout=%dms",
        settings.mysql_user,
        settings.mysql_host,
        settings.mysql_port,
        settings.mysql_db,
        settings.statement_timeout_ms,
    )
    return eng


# Engine construction is lazy — no connection until first `engine.connect()`.
engine: Engine = _create_engine()
