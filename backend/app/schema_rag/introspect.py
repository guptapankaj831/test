"""MySQL `information_schema` introspection — columns, FKs, sample rows per table."""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel
from sqlalchemy import text

from app.config import settings
from app.db import engine

logger = logging.getLogger(__name__)

# Table names aren't bindable; whitelist before splicing into SQL.
_IDENT_RE = re.compile(r"^[A-Za-z0-9_$]+$")

# Per-cell cap so a TEXT/BLOB column can't blow up the LLM prompt.
_CELL_MAX_LEN = 200


class ColumnInfo(BaseModel):
    column_name: str
    data_type: str
    is_nullable: bool
    is_primary_key: bool
    column_comment: str


class ForeignKey(BaseModel):
    column_name: str
    referenced_table: str
    referenced_column: str


class TableInfo(BaseModel):
    name: str
    columns: list[ColumnInfo]
    foreign_keys: list[ForeignKey]
    sample_rows: list[dict]


def list_tables(db: str) -> list[str]:
    """Return all base-table names in the given MySQL database, ordered alphabetically."""
    query = text(
        "SELECT TABLE_NAME "
        "FROM information_schema.tables "
        "WHERE TABLE_SCHEMA = :db AND TABLE_TYPE = 'BASE TABLE' "
        "ORDER BY TABLE_NAME"
    )
    with engine.connect() as conn:
        result = conn.execute(query, {"db": db})
        return [row[0] for row in result]


def get_columns(db: str, table: str) -> list[ColumnInfo]:
    """Return ordered column metadata for `db.table` as typed `ColumnInfo` rows."""
    query = text(
        "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_KEY, COLUMN_COMMENT "
        "FROM information_schema.columns "
        "WHERE TABLE_SCHEMA = :db AND TABLE_NAME = :table "
        "ORDER BY ORDINAL_POSITION"
    )
    with engine.connect() as conn:
        result = conn.execute(query, {"db": db, "table": table})
        return [
            ColumnInfo(
                column_name=row.COLUMN_NAME,
                data_type=row.DATA_TYPE,
                is_nullable=(row.IS_NULLABLE == "YES"),
                is_primary_key=(row.COLUMN_KEY == "PRI"),
                column_comment=row.COLUMN_COMMENT,
            )
            for row in result
        ]


def get_foreign_keys(db: str, table: str) -> list[ForeignKey]:
    """Return FK edges from `db.table`. Filters key_column_usage on REFERENCED_TABLE_NAME IS NOT NULL."""
    query = text(
        "SELECT COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
        "FROM information_schema.key_column_usage "
        "WHERE TABLE_SCHEMA = :db "
        "  AND TABLE_NAME = :table "
        "  AND REFERENCED_TABLE_NAME IS NOT NULL "
        "ORDER BY ORDINAL_POSITION"
    )
    with engine.connect() as conn:
        result = conn.execute(query, {"db": db, "table": table})
        return [
            ForeignKey(
                column_name=row.COLUMN_NAME,
                referenced_table=row.REFERENCED_TABLE_NAME,
                referenced_column=row.REFERENCED_COLUMN_NAME,
            )
            for row in result
        ]


def _coerce_cell(value: Any) -> Any:
    """Make a row cell JSON-safe and length-capped (Decimal/datetime/bytes → str)."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        text_value = f"<{len(value)} bytes>"
    else:
        text_value = str(value)
    if len(text_value) > _CELL_MAX_LEN:
        text_value = text_value[: _CELL_MAX_LEN - 1] + "…"
    return text_value


def get_sample_rows(db: str, table: str, limit: int = 5) -> list[dict]:
    """Return up to `limit` rows from `db.table` as JSON-safe dicts."""
    if not _IDENT_RE.fullmatch(db) or not _IDENT_RE.fullmatch(table):
        raise ValueError(f"Refusing to query unsafe identifier: {db}.{table!r}")

    sql = text(f"SELECT * FROM `{db}`.`{table}` LIMIT :limit")
    with engine.connect() as conn:
        rows = conn.execute(sql, {"limit": int(limit)}).mappings().all()

    return [{k: _coerce_cell(v) for k, v in row.items()} for row in rows]


def introspect_database(db: str | None = None) -> list[TableInfo]:
    """Assemble columns + FKs + sample rows for every base table in `db` (defaults to `settings.mysql_db`)."""
    target = db or settings.mysql_db
    tables = list_tables(target)
    logger.info("introspect: %d table(s) found in `%s`", len(tables), target)
    print("introspect: %d table(s) found in `%s`", len(tables), target)
    print(f"\nTable Names: {tables}\n")

    out: list[TableInfo] = []
    for name in tables:
        info = TableInfo(
            name=name,
            columns=get_columns(target, name),
            foreign_keys=get_foreign_keys(target, name),
            sample_rows=get_sample_rows(target, name),
        )
        print(f"\nInfo: {info}\n")
        logger.debug(
            "introspect: %s — %d col(s), %d fk(s), %d sample row(s)",
            name,
            len(info.columns),
            len(info.foreign_keys),
            len(info.sample_rows),
        )
        out.append(info)

    return out
