from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from app.config import settings  # noqa: F401 — triggers logging + env setup at import
from app.graph.graph import research_graph
from app.graph.state import initial_state
from app.schemas.research import ResearchRequest

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Multi-Agent Research Assistant",
    description="Planner / Researcher / Writer / Critic loop over a LangGraph, streamed as SSE.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _draft_text(draft: Any) -> str:
    return draft.content if hasattr(draft, "content") else (draft or "")


@app.post("/research")
async def research(req: ResearchRequest, request: Request) -> StreamingResponse:
    run_id = uuid.uuid4().hex[:8]
    state = initial_state(req.query, max_iterations=req.max_iterations)
    logger.info(
        "[%s] /research start: query=%r max_iterations=%d",
        run_id,
        req.query,
        req.max_iterations,
    )

    async def event_gen() -> AsyncIterator[str]:
        started = time.monotonic()
        researcher_runs = 0
        writer_runs = 0
        total_findings = 0
        try:
            async for update in research_graph.astream(state, stream_mode="updates"):
                if await request.is_disconnected():
                    logger.info("[%s] client disconnected; stopping graph", run_id)
                    break

                for node_name, delta in update.items():
                    if node_name == "planner_node":
                        plan = delta.get("plan")
                        if plan is None:
                            continue
                        yield _sse("plan", plan.model_dump(mode="json"))

                    elif node_name == "researcher_node":
                        researcher_runs += 1
                        new = delta.get("findings") or []
                        total_findings += len(new)
                        yield _sse(
                            "research_progress",
                            {
                                "iteration": researcher_runs,
                                "new_findings": [f.model_dump(mode="json") for f in new],
                                "total_findings": total_findings,
                                "gap_driven": researcher_runs > 1,
                            },
                        )

                    elif node_name == "writer_node":
                        writer_runs += 1
                        yield _sse(
                            "draft",
                            {
                                "iteration": writer_runs,
                                "text": _draft_text(delta.get("draft", "")),
                            },
                        )

                    elif node_name == "critic_node":
                        critiques = delta.get("critiques") or []
                        if not critiques:
                            continue
                        c = critiques[-1]
                        yield _sse(
                            "critique",
                            {
                                "iteration": c.iteration,
                                "verdict": c.verdict,
                                "reasoning": c.reasoning,
                                "gaps": c.gaps,
                                "unsupported_claims": c.unsupported_claims,
                            },
                        )

            elapsed = time.monotonic() - started
            logger.info(
                "[%s] /research done in %.1fs: iterations=%d findings=%d",
                run_id,
                elapsed,
                writer_runs,
                total_findings,
            )
            yield _sse(
                "done",
                {
                    "total_iterations": writer_runs,
                    "total_findings": total_findings,
                },
            )
        except Exception as exc:
            logger.exception("[%s] /research failed: %s", run_id, exc)
            yield _sse("error", {"message": str(exc)})

    return StreamingResponse(event_gen(), media_type="text/event-stream")


def run() -> None:
    """Entrypoint registered as the `mara-api` console script."""
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=False)
