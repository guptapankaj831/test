from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchRequest(BaseModel):
    query: str = Field(..., min_length=5, description="Research question to investigate.")
    max_iterations: int = Field(3, ge=1, le=5, description="Maximum critic loops.")
