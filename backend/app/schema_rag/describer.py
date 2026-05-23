"""LLM auto-describer — turns a `TableInfo` into typed prose for the schema RAG index."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel

from app.llm import get_llm
from app.schema_rag.introspect import TableInfo

logger = logging.getLogger(__name__)

# Load once at import — the prompt is a static asset, not a runtime input.
_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "describer.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")


class ColumnDescription(BaseModel):
    column_name: str
    description: str


class TableDescription(BaseModel):
    table_description: str
    column_descriptions: list[ColumnDescription]


def _format_columns(table: TableInfo) -> str:
    lines: list[str] = []
    for c in table.columns:
        tags = []
        if c.is_primary_key:
            tags.append("PK")
        if c.is_nullable:
            tags.append("nullable")
        suffix = f" [{', '.join(tags)}]" if tags else ""
        comment = f" — {c.column_comment}" if c.column_comment else ""
        lines.append(f"- {c.column_name} ({c.data_type}){suffix}{comment}")
    return "\n".join(lines)


def _format_foreign_keys(table: TableInfo) -> str:
    if not table.foreign_keys:
        return "(none)"
    return "\n".join(
        f"- {fk.column_name} -> {fk.referenced_table}.{fk.referenced_column}"
        for fk in table.foreign_keys
    )


def _format_sample_rows(table: TableInfo) -> str:
    if not table.sample_rows:
        return "(no rows)"
    return json.dumps(table.sample_rows, ensure_ascii=False, indent=2, default=str)


def describe_table(table: TableInfo) -> TableDescription:
    """Render the prompt for one table and ask the LLM for structured prose."""
    prompt = _PROMPT_TEMPLATE.format(
        table_name=table.name,
        columns=_format_columns(table),
        foreign_keys=_format_foreign_keys(table),
        sample_rows=_format_sample_rows(table),
    )
    print(f"\ndescribe_table_prompt: {prompt}\n")
    structured = get_llm().with_structured_output(TableDescription)
    result = structured.invoke(prompt)
    logger.debug(
        "describe_table: %s — %d column description(s)",
        table.name,
        len(result.column_descriptions),
    )

    return result
