"""M9: the copilot loop, its grounding checks and the endpoint, with a scripted fake LLM."""

import json
from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from khataiq.copilot.llm import LLMResponse, ToolCall, get_llm
from khataiq.copilot.service import DECLINE, MAX_TOOL_CALLS
from khataiq.models import CopilotMessage, User
from khataiq.models.enums import UserRole
from khataiq.pipeline.parsers.demo_csv import render_demo_csv
from khataiq.principal import Principal
from tests.integration import factories as f
from tests.integration.conftest import People, login
from tests.integration.pipeline_helpers import Shop, run_pipeline, upload

pytestmark = pytest.mark.usefixtures("local_store")

Step = Callable[[list[dict[str, Any]]], LLMResponse]


class FakeLLM:
    """Plays back scripted steps; each step sees the conversation so far."""

    def __init__(self, steps: list[Step]) -> None:
        self.steps = list(steps)
        self.seen: list[list[dict[str, Any]]] = []

    def chat(self, *, system, messages, tools, answer_schema) -> LLMResponse:
        self.seen.append(list(messages))
        return self.steps.pop(0)(messages)


def call(*calls: tuple[str, dict[str, Any]]) -> Step:
    tool_calls = [ToolCall(f"t{i}", name, args) for i, (name, args) in enumerate(calls)]
    return lambda _: LLMResponse("tool_use", "", tool_calls, [{"type": "text", "text": "..."}])


def answer(build: Callable[[list[dict[str, Any]]], dict[str, Any]]) -> Step:
    def step(messages):
        text = json.dumps(build(messages))
        return LLMResponse("end_turn", text, [], [{"type": "text", "text": text}])
    return step


def last_tool_result(messages) -> dict[str, Any]:
    results = [m for m in messages if m["role"] == "user" and isinstance(m["content"], list)]
    return json.loads(results[-1]["content"][0]["content"])


@pytest.fixture()
def business(api, people: People, owner_session: Session) -> int:
    owner = owner_session.scalar(select(User).where(User.email == people.owner1))
    b = f.business(owner_session, people.org_a, owner.id)
    a = f.account(owner_session, people.org_a, b.id)
    owner_session.commit()
    shop = Shop(Principal(owner.id, people.org_a, UserRole.OWNER), b.id, a.id)
    upload(shop, render_demo_csv(1_000_000, [
        (date(2026, 10, 2), "UPI/RAMESH/ramesh12@okaxis/412300000001", 0, 2_500_000),
        (date(2026, 10, 3), "UPI/SITA/sita34@okaxis/412300000002", 0, 1_234_550),
        (date(2026, 10, 9), "NEFT/HDFC0000001/SHARMA TRADERS", 500_000, 0),
    ]))
    run_pipeline()
    return b.id


def use(api, fake: FakeLLM) -> FakeLLM:
    api.app.dependency_overrides[get_llm] = lambda: fake
    return fake


def ask(api, people: People, business: int, question="How much came in?", **extra):
    return api.post(f"/v1/businesses/{business}/copilot", headers=login(api, people.officer),
                    json={"question": question, **extra})


def test_a_grounded_answer_is_returned_with_citations(api, people, business, owner_session):
    def build(messages):
        month = last_tool_result(messages)["months"][0]
        gross = month["gross_inflow_paise"] // 100
        return {"answer": f"October gross inflow was ₹{gross:,}.",
                "citations": [{"type": "metric", "id": month["id"]}]}

    use(api, FakeLLM([call(("get_monthly_metrics", {})), answer(build)]))
    r = ask(api, people, business)
    body = r.json()
    assert r.status_code == 200 and body["grounded"] is True
    assert body["answer"] == "October gross inflow was ₹37,345."  # 25,000 + 12,345.50, rounded
    assert body["citations"] == [{"type": "metric", "id": 202610}]
    assert owner_session.scalar(select(func.count()).select_from(CopilotMessage)) == 2


def test_citing_an_id_no_tool_returned_is_retried_then_declined(api, people, business):
    bad = answer(lambda _: {"answer": "₹25,000 came from Ramesh.",
                            "citations": [{"type": "txn", "id": 999_999}]})
    fake = use(api, FakeLLM([call(("list_transactions", {"direction": "credit"})), bad, bad]))
    body = ask(api, people, business).json()
    assert (body["answer"], body["citations"], body["grounded"]) == (DECLINE, [], False)
    feedback = fake.seen[-1][-1]["content"]
    assert "txn:999999 was not returned" in feedback


def test_a_made_up_figure_is_rejected_and_the_retry_can_fix_it(api, people, business):
    def wrong(messages):
        txn = last_tool_result(messages)["transactions"][0]
        return {"answer": "₹99,000 came in.", "citations": [{"type": "txn", "id": txn["id"]}]}

    def right(messages):
        tool_results = [m for m in messages if m["role"] == "user"
                        and isinstance(m["content"], list)]
        rows = json.loads(tool_results[-1]["content"][0]["content"])["transactions"]
        ramesh = next(r for r in rows if r["amount_paise"] == 2_500_000)
        return {"answer": "₹25,000 came from Ramesh.",
                "citations": [{"type": "txn", "id": ramesh["id"]}]}

    use(api, FakeLLM([call(("list_transactions", {"direction": "credit"})), answer(wrong),
                      answer(right)]))
    body = ask(api, people, business).json()
    assert body["grounded"] is True and body["answer"] == "₹25,000 came from Ramesh."


def test_tool_calls_are_capped(api, people, business):
    seven = [call(("get_upload_status", {})) for _ in range(MAX_TOOL_CALLS + 1)]
    fake = use(api, FakeLLM([*seven, answer(lambda _: {"answer": "Done.", "citations": []})]))
    assert ask(api, people, business).json()["answer"] == "Done."
    capped = fake.seen[-1][-1]["content"][0]
    assert capped["is_error"] and "limit" in capped["content"]


def test_bad_tool_arguments_come_back_as_a_tool_error(api, people, business):
    fake = use(api, FakeLLM([call(("list_transactions", {"limit": 500})),
                             answer(lambda _: {"answer": "No data.", "citations": []})]))
    ask(api, people, business)
    result = fake.seen[-1][-1]["content"][0]
    assert result["is_error"] and "invalid arguments" in result["content"]


def test_follow_up_questions_carry_the_conversation(api, people, business):
    fake = use(api, FakeLLM([answer(lambda _: {"answer": "First.", "citations": []}),
                             answer(lambda _: {"answer": "Second.", "citations": []})]))
    first = ask(api, people, business, "One?").json()
    ask(api, people, business, "Two?", conversation_id=first["conversation_id"])
    replay = fake.seen[-1]
    assert [m["role"] for m in replay] == ["user", "assistant", "user"]
    assert replay[0]["content"] == "One?" and replay[2]["content"] == "Two?"


def test_a_refusal_is_declined_without_retrying(api, people, business):
    refuse = lambda _: LLMResponse("refusal", "", [], [])  # noqa: E731
    fake = use(api, FakeLLM([refuse]))
    assert ask(api, people, business).json()["answer"] == DECLINE
    assert len(fake.seen) == 1


def test_no_api_key_is_503(api, people, business):
    r = ask(api, people, business)
    assert r.status_code == 503 and "KHATAIQ_LLM_API_KEY" in r.json()["detail"]


def test_owners_cannot_use_the_copilot(api, people, business):
    r = api.post(f"/v1/businesses/{business}/copilot", headers=login(api, people.owner1),
                 json={"question": "x"})
    assert r.status_code == 403
