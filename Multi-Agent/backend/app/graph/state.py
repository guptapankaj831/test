from __future__ import annotations

from datetime import datetime, timezone
from operator import add
from typing import Annotated, Literal, TypedDict

from pydantic import BaseModel, Field, HttpUrl

from app.config import settings


class SubQuestion(BaseModel):
    id: int = Field(..., ge=1)
    question: str = Field(..., min_length=5)
    rationale: str = ""


class ResearchPlan(BaseModel):
    objective: str
    success_criteria: list[str] = Field(default_factory=list)
    sub_questions: list[SubQuestion]


class Finding(BaseModel):
    sub_question_id: int
    claim: str
    evidence: str
    url: HttpUrl
    source_title: str | None = None
    retrieved_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Critique(BaseModel):
    iteration: int
    gaps: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    verdict: Literal["continue", "done"]
    reasoning: str = ""


# `findings` and `critiques` use the `add` reducer so nodes can append without
# overwriting earlier values across loop iterations.
class ResearchState(TypedDict, total=False):
    query: str
    plan: ResearchPlan | None
    findings: Annotated[list[Finding], add]
    draft: str
    critiques: Annotated[list[Critique], add]
    iteration: int
    max_iterations: int


def initial_state(query: str, max_iterations: int | None = None) -> ResearchState:
    return ResearchState(
        query=query,
        plan=None,
        findings=[],
        draft="",
        critiques=[],
        iteration=0,
        max_iterations=max_iterations or settings.max_iterations_default,
    )
