"""One copilot question: a tool loop, a grounding check, one retry, then answer or decline.

    question -> LLM (may call up to 6 read-only tools) -> JSON {answer, citations}
             -> grounding check against this turn's tool results
             -> pass: return it
             -> fail: tell the model exactly what failed, let it try once more
             -> fail again: return a fixed "couldn't answer" and log the failure
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from khataiq.copilot.grounding import Citation, Evidence, check
from khataiq.copilot.llm import LLMClient, LLMResponse
from khataiq.copilot.tools import TOOLS, ToolContext, ToolError, run_tool
from khataiq.errors import NotFound
from khataiq.models import CopilotMessage
from khataiq.principal import Principal
from khataiq.services import access

log = logging.getLogger(__name__)

MAX_TOOL_CALLS = 6
MAX_MODEL_TURNS = 12  # a hard stop for the loop, independent of the tool budget
DECLINE = "I couldn't answer that from the available data."

SYSTEM_PROMPT = """\
You help a loan officer understand the cash flow of one small business, using only the data \
your tools return. The business is already selected; you never need its id.

How to answer:
- Look the data up with the tools before answering. Use at most 6 tool calls.
- Reply with JSON only: {"answer": "...", "citations": [{"type": "txn" | "metric", "id": ...}]}.
- Cite every transaction (type "txn", its id) and every monthly metric row (type "metric", the \
month's id) that a figure in your answer comes from. Cite only ids a tool returned.
- Write amounts in rupees with Indian digit grouping, like ₹12,345 or ₹1,23,456.50. Every \
amount must be a value in the rows you cite, or a sum or difference of at most three of them. \
Tool amounts are in paise: divide by 100.
- When a month has uncertain_paise above zero, say how much of the inflow is uncertain.
- Answer only about this business. Never recommend whether to lend, and never give a credit \
score or a verdict on fraud: describe the evidence and leave the decision to the officer.
- If the data doesn't answer the question, say so plainly."""

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"type": {"type": "string", "enum": ["txn", "metric"]},
                               "id": {"type": "integer"}},
                "required": ["type", "id"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "citations"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Answer:
    answer: str
    citations: list[Citation]
    conversation_id: uuid.UUID
    grounded: bool


class _Loop:
    def __init__(self, llm: LLMClient, ctx: ToolContext) -> None:
        self.llm = llm
        self.ctx = ctx
        self.tool_calls = 0
        self.tools = [spec.definition() for spec in TOOLS.values()]

    def run(self, messages: list[dict[str, Any]]) -> LLMResponse:
        for _ in range(MAX_MODEL_TURNS):
            response = self.llm.chat(system=SYSTEM_PROMPT, messages=messages, tools=self.tools,
                                     answer_schema=ANSWER_SCHEMA)
            if response.stop_reason != "tool_use":
                return response
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",
                             "content": [self._call(c.id, c.name, c.input)
                                         for c in response.tool_calls]})
        return LLMResponse("max_turns", "", [])

    def _call(self, call_id: str, name: str, raw: dict[str, Any]) -> dict[str, Any]:
        if self.tool_calls >= MAX_TOOL_CALLS:
            return {"type": "tool_result", "tool_use_id": call_id, "is_error": True,
                    "content": "Tool call limit reached. Answer with the data you have."}
        self.tool_calls += 1
        try:
            result = run_tool(self.ctx, name, raw)
        except ToolError as exc:
            return {"type": "tool_result", "tool_use_id": call_id, "is_error": True,
                    "content": str(exc)}
        return {"type": "tool_result", "tool_use_id": call_id,
                "content": json.dumps(result, default=str)}


def _parse(response: LLMResponse) -> tuple[str, list[Citation]] | None:
    if response.stop_reason != "end_turn":
        return None
    try:
        data = json.loads(response.text)
        return str(data["answer"]), [Citation(str(c["type"]), int(c["id"]))
                                     for c in data["citations"]]
    except (ValueError, KeyError, TypeError):
        return None


def _history(s: Session, conversation_id: uuid.UUID, business_id: int,
             user_id: int) -> list[dict[str, Any]]:
    rows = s.scalars(select(CopilotMessage).where(
        CopilotMessage.conversation_id == conversation_id).order_by(CopilotMessage.id)).all()
    if rows and (rows[0].business_id != business_id or rows[0].user_id != user_id):
        raise NotFound("conversation not found")
    return [{"role": r.role, "content": r.content["text"] if r.role == "user"
             else json.dumps({"answer": r.content["answer"],
                              "citations": r.content["citations"]})}
            for r in rows]


def ask(s: Session, p: Principal, business_id: int, question: str,
        conversation_id: uuid.UUID | None, llm: LLMClient) -> Answer:
    access.get_business(s, p, business_id)
    conversation = conversation_id or uuid.uuid4()
    messages = _history(s, conversation, business_id, p.id) + [
        {"role": "user", "content": question}]
    evidence = Evidence()
    loop = _Loop(llm, ToolContext(s, p, business_id, evidence))

    grounded = False
    answer, citations = DECLINE, []
    for attempt in (1, 2):
        response = loop.run(messages)
        parsed = _parse(response)
        if parsed is None:
            problems: tuple[str, ...] = (f"no valid JSON answer (stop: {response.stop_reason})",)
        else:
            result = check(parsed[0], parsed[1], evidence)
            if result.ok:
                answer, citations, grounded = parsed[0], parsed[1], True
                break
            problems = result.problems
        log.warning("copilot answer failed grounding",
                    extra={"attempt": attempt, "problems": list(problems),
                           "business_id": business_id})
        if attempt == 1 and response.stop_reason == "end_turn":
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": (
                "Your answer failed the server's checks:\n- " + "\n- ".join(problems)
                + "\nAnswer again. Use only figures from tool results and cite their rows.")})
        else:
            break

    s.add(CopilotMessage(org_id=p.org_id, conversation_id=conversation,
                         business_id=business_id, user_id=p.id, role="user",
                         content={"text": question}))
    s.add(CopilotMessage(org_id=p.org_id, conversation_id=conversation,
                         business_id=business_id, user_id=p.id, role="assistant",
                         content={"answer": answer, "grounded": grounded,
                                  "citations": [{"type": c.type, "id": c.id}
                                                for c in citations]}))
    return Answer(answer, citations, conversation, grounded)
