"""FastAPI entrypoint — POST /ask (SSE event stream) + GET /health."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from app.chain import run_chain
from app.schema_rag.indexer import ensure_index
from app.schemas.ask import AskRequest

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logger.info("startup: ensuring schema index...")
    ensure_index()
    logger.info("startup: ready")
    yield


app = FastAPI(title="NL-to-SQL Analyst", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


async def _sse_stream(question: str) -> AsyncIterator[str]:
    """Wrap `run_chain` events as SSE frames; emit a fatal `error` frame if the chain itself crashes."""
    try:
        async for event in run_chain(question):
            payload = json.dumps(event["data"], ensure_ascii=False)
            yield f"event: {event['event']}\ndata: {payload}\n\n"
    except Exception as e:
        logger.exception("chain crashed unexpectedly")
        payload = json.dumps({"stage": "fatal", "message": str(e)})
        yield f"event: error\ndata: {payload}\n\n"


@app.post("/ask")
async def ask(req: AskRequest) -> StreamingResponse:
    logger.info("ask: %r", req.question)
    return StreamingResponse(_sse_stream(req.question), media_type="text/event-stream")
