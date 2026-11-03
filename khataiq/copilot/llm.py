"""A small interface over the LLM provider, so the copilot loop can be tested with a fake."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from khataiq.config import get_settings
from khataiq.errors import ServiceUnavailable


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    stop_reason: str  # end_turn | tool_use | max_tokens | refusal | ...
    text: str
    tool_calls: list[ToolCall]
    # The assistant content exactly as returned; appended back unchanged on the next request
    # (thinking blocks included).
    content: list[Any] = field(default_factory=list)


class LLMClient(Protocol):
    def chat(self, *, system: str, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]], answer_schema: dict[str, Any]) -> LLMResponse: ...


class AnthropicLLM:
    """Claude via the Anthropic Messages API.

    * output_config.format makes the final answer schema-valid JSON;
    * effort is set explicitly (this model defaults to medium; the copilot reads data and
      writes a short cited answer, so medium is enough);
    * server-side refusal fallbacks are on: if the model declines on a safety classifier,
      the API retries on a fallback model it chooses, inside the same call.
    """

    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key, max_retries=2, timeout=60.0)
        self.model = model

    def chat(self, *, system: str, messages: list[dict[str, Any]],
             tools: list[dict[str, Any]], answer_schema: dict[str, Any]) -> LLMResponse:
        # Plain dicts in, so these are typed loosely; the API validates their shape.
        strict_tools: Any = [{**tool, "strict": True} for tool in tools]
        history: Any = messages
        output_config: Any = {"effort": "medium",
                              "format": {"type": "json_schema", "schema": answer_schema}}
        response = self.client.beta.messages.create(
            model=self.model,
            max_tokens=16_000,
            system=system,
            messages=history,
            tools=strict_tools,
            output_config=output_config,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in response.content
                 if b.type == "tool_use"]
        return LLMResponse(str(response.stop_reason), text, calls, list(response.content))


def get_llm() -> LLMClient:
    """FastAPI dependency. No API key configured -> 503, as the spec requires."""
    settings = get_settings()
    if settings.llm_api_key is None:
        raise ServiceUnavailable("the copilot is not configured (KHATAIQ_LLM_API_KEY is unset)")
    return AnthropicLLM(settings.llm_api_key.get_secret_value(), settings.llm_model)


def parse_answer(text: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(text)
    return data
