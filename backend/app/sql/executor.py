"""Safe execute against the read-only engine — clamped LIMIT, JSON-safe rows."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlglot import expressions as exp

from app.config import settings
from app.db import engine

logger = logging.getLogger(__name__)


class ExecutionResult(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    sql_executed: str


class SqlExecutionError(RuntimeError):
    """Raised when an AST-validated SELECT fails at runtime."""

    def __init__(self, message: str, *, sql_executed: str, db_message: str) -> None:
        super().__init__(message)
        self.sql_executed = sql_executed
        self.db_message = db_message


def execute(ast: exp.Expression) -> ExecutionResult:
    """Run the validated AST. Returns rows + column names. Raises SqlExecutionError on DB error."""
    cap = settings.result_row_cap

    # Clamp root LIMIT to cap (inject if absent); query with effective+1 to detect truncation.
    existing = ast.args.get("limit")
    user_limit: int | None = None
    if existing is not None and existing.expression is not None:
        try:
            user_limit = int(existing.expression.this)
        except (TypeError, ValueError, AttributeError):
            user_limit = None
    effective = min(user_limit, cap) if user_limit is not None else cap
    sql_executed = ast.limit(effective + 1).sql(dialect="mysql")

    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql_executed))
            columns = [d[0] for d in (result.cursor.description or [])]
            raw_rows = result.mappings().all()
    except DBAPIError as e:
        db_message = str(getattr(e, "orig", e))
        logger.warning("execute failed: %s | sql=%s", db_message, sql_executed)
        raise SqlExecutionError(
            f"{db_message} | sql={sql_executed}",
            sql_executed=sql_executed,
            db_message=db_message,
        ) from e

    truncated = len(raw_rows) > effective
    rows = [{k: _coerce_cell(v) for k, v in row.items()} for row in raw_rows[:effective]]

    logger.info("execute ok: rows=%d truncated=%s cols=%d", len(rows), truncated, len(columns))
    return ExecutionResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        sql_executed=sql_executed,
    )


def _coerce_cell(value: Any) -> Any:
    """Make a result cell JSON-safe. No length cap — display truncation is the UI's call."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return str(value)
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, dict):
        return {k: _coerce_cell(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_coerce_cell(v) for v in value]
    return str(value)
