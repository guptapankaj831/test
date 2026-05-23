"""LangChain-orchestrated pipeline: retrieve → generate → validate → execute → summarize.

Yields semantic events (schema / sql / result / summary / done / error) for the SSE layer
in main.py. SQL generation is a `RunnableSequence` (PromptTemplate | structured-LLM); the
outer flow is an async generator because per-error-type retries + event emission don't fit
cleanly in a Runnable.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, AsyncIterator

from langchain_core.prompts import PromptTemplate

from app.config import settings
from app.llm import get_llm
from app.schema_rag.indexer import retrieve
from app.schemas.ask import SqlPlan
from app.sql.executor import ExecutionResult, SqlExecutionError, execute
from app.sql.validator import SqlValidationError, validate_select_only
from app.summarizer import summarize

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "sql_generator.md"
_PROMPT_TEMPLATE = PromptTemplate.from_template(_PROMPT_PATH.read_text(encoding="utf-8"))
_generate_chain = _PROMPT_TEMPLATE | get_llm().with_structured_output(SqlPlan)


def _format_schema_slice(docs: list[dict[str, Any]]) -> str:
    """Group retrieved docs by table; render as a compact text block for the prompt."""
    by_table: dict[str, dict[str, Any]] = {}
    for doc in docs:
        meta = doc["metadata"]
        table = meta["table"]
        entry = by_table.setdefault(table, {"desc": "", "columns": []})
        if meta["kind"] == "table":
            entry["desc"] = doc["text"]
        else:
            entry["columns"].append((meta["column"], doc["text"]))

    if not by_table:
        return "(no schema retrieved)"

    lines: list[str] = []
    for table, entry in by_table.items():
        lines.append(f"## {table}")
        if entry["desc"]:
            lines.append(entry["desc"])
        for col_name, col_desc in entry["columns"]:
            lines.append(f"- {col_name}: {col_desc}")
        lines.append("")
    return "\n".join(lines).strip()


async def run_chain(question: str) -> AsyncIterator[dict[str, Any]]:
    """Run the full pipeline; yield semantic events. Stops on first unrecoverable error."""
    started = time.monotonic()

    # 1. Retrieve schema slice.
    docs = retrieve(question)
    schema_slice = _format_schema_slice(docs)
    yield {
        "event": "schema",
        "data": [
            {
                "id": d["id"],
                "kind": d["metadata"]["kind"],
                "table": d["metadata"]["table"],
                "column": d["metadata"].get("column"),
                "distance": d["distance"],
            }
            for d in docs
        ],
    }

    # 2-4. Generate → validate → execute, with per-error-type retries.
    previous_error = "(none)"
    validation_retries = 0
    execution_retries = 0
    plan: SqlPlan | None = None
    result: ExecutionResult | None = None

    while True:
        try:
            plan = await _generate_chain.ainvoke({
                "question": question,
                "schema_slice": schema_slice,
                "previous_error": previous_error,
            })
        except Exception as e:
            logger.exception("sql generation failed")
            yield {"event": "error", "data": {"stage": "generate", "message": str(e)}}
            return

        try:
            ast = validate_select_only(plan.sql)
        except SqlValidationError as e:
            logger.info("validation failed (retry %d): %s", validation_retries, e)
            if validation_retries >= settings.sql_validation_max_retries:
                yield {"event": "error", "data": {"stage": "validate", "message": str(e), "sql": plan.sql}}
                return
            validation_retries += 1
            previous_error = f"Validation rejected this SQL:\n{plan.sql}\nError: {e}"
            continue

        yield {"event": "sql", "data": {"sql": plan.sql, "reasoning": plan.reasoning}}

        try:
            result = execute(ast)
            break
        except SqlExecutionError as e:
            logger.info("execution failed (retry %d): %s", execution_retries, e.db_message)
            if execution_retries >= settings.sql_execution_max_retries:
                yield {"event": "error", "data": {"stage": "execute", "message": e.db_message, "sql": e.sql_executed}}
                return
            execution_retries += 1
            previous_error = f"Execution failed for this SQL:\n{e.sql_executed}\nDB error: {e.db_message}"
            continue

    yield {"event": "result", "data": result.model_dump()}

    # 5. Streaming summary.
    async for token in summarize(question, result):
        yield {"event": "summary", "data": token}

    yield {
        "event": "done",
        "data": {
            "elapsed_s": round(time.monotonic() - started, 2),
            "validation_retries": validation_retries,
            "execution_retries": execution_retries,
        },
    }
