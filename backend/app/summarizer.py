"""Token-streamed natural-language summary of an ExecutionResult."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from app.llm import get_llm
from app.sql.executor import ExecutionResult

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "summarizer.md"
_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")


def _build_preview(rows: list[dict[str, Any]]) -> str:
    """JSON-lines preview — all rows if <=15, else first 10 + omission marker + last 5."""
    if len(rows) <= 15:
        return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
    head = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows[:10])
    tail = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows[-5:])
    return f"{head}\n... ({len(rows) - 15} rows omitted) ...\n{tail}"


async def summarize(question: str, result: ExecutionResult) -> AsyncIterator[str]:
    """Stream a short, grounded answer derived from `result` and the original `question`."""
    prompt = _PROMPT_TEMPLATE.format(
        question=question,
        sql=result.sql_executed,
        columns=", ".join(result.columns) or "(none)",
        row_count=result.row_count,
        truncation_note=" (capped — more rows exist)" if result.truncated else "",
        row_preview=_build_preview(result.rows) or "(no rows)",
    )
    logger.debug("summarize: rows=%d truncated=%s", result.row_count, result.truncated)
    async for chunk in get_llm().astream(prompt):
        content = getattr(chunk, "content", "")
        if content:
            yield content
