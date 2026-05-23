"""Pydantic models for the /ask request/response surface."""

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """Inbound payload for POST /ask."""

    question: str = Field(..., min_length=1, description="Natural-language question for the analyst.")


class SqlPlan(BaseModel):
    """Structured output from the SQL generator — the SQL plus a short rationale."""

    sql: str = Field(..., description="A single read-only SELECT against the available schema.")
    reasoning: str = Field(..., description="1-2 sentences explaining the join path / aggregation.")
