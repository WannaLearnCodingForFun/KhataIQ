"""The officer copilot."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from khataiq.api.deps import Ctx, officer_ctx, rate_limit
from khataiq.copilot.llm import LLMClient, get_llm
from khataiq.copilot.service import ask
from khataiq.ratelimit import copilot_bucket, general_bucket

router = APIRouter(prefix="/v1", tags=["copilot"],
                   dependencies=[Depends(rate_limit(general_bucket()))])


class CopilotIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    conversation_id: uuid.UUID | None = None


class CitationOut(BaseModel):
    type: Literal["txn", "metric"]
    id: int


class CopilotOut(BaseModel):
    answer: str
    citations: list[CitationOut]
    conversation_id: uuid.UUID
    grounded: bool


@router.post("/businesses/{business_id}/copilot", response_model=CopilotOut,
             dependencies=[Depends(rate_limit(copilot_bucket()))])
def copilot(business_id: int, body: CopilotIn, c: Ctx = Depends(officer_ctx),
            llm: LLMClient = Depends(get_llm)) -> CopilotOut:
    # One read transaction spans the model's tool calls, so every tool in one answer sees the
    # same snapshot of the ledger; the question and answer are written at the end.
    with c.session() as s:
        result = ask(s, c.user, business_id, body.question, body.conversation_id, llm)
    return CopilotOut(answer=result.answer,
                      citations=[CitationOut(type=x.type, id=x.id)  # type: ignore[arg-type]
                                 for x in result.citations],
                      conversation_id=result.conversation_id, grounded=result.grounded)
