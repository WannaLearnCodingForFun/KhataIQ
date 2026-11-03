# Copilot spec

The copilot answers an officer's questions about one business, using only that business's data,
and every figure in the answer is backed by a citation the server can check.

## LLM client
- `copilot/llm.py` wraps the Anthropic Python SDK behind a small interface `LLMClient.chat(messages,
  tools) -> response`, so tests use a fake. Model name and API key come from settings
  (`KHATAIQ_LLM_MODEL`, `KHATAIQ_LLM_API_KEY`); nothing hard-coded.
- If no API key is set, the endpoint returns 503 with a clear problem+json message.

## Tools (read-only, org- and business-scoped; the business id is injected by the server, never by the model)
| Tool | Args | Returns |
| --- | --- | --- |
| get_monthly_metrics | `from_month?, to_month?` | metric rows with ids |
| list_transactions | `from?, to?, label?, direction?, min_paise?, limit≤50` | rows with ids |
| get_flags | `status?` | flags with evidence txn ids |
| get_evidence | `kind?, level?` | evidence links |
| get_upload_status | — | uploads and reconciliation results |

## Answer format
The model must reply as JSON: `{"answer": str, "citations": [{"type": "txn"|"metric", "id": int}]}`.
Amounts in the answer are written as `₹12,345` or `₹12,345.50`.

## Grounding checker (`copilot/grounding.py`)
1. Every cited id must appear in a tool result from this conversation turn.
2. Every rupee amount in `answer` must equal (after converting to paise) a value present in the cited
   rows, or a sum/difference of at most 3 of those values.
3. Pass → return. Fail → send the model the specific failure once and retry. Fail again → return
   `{"answer": "I couldn't answer that from the available data.", "citations": []}` and log the failure.

## Other limits
- Max 6 tool calls per question; 20 questions per officer per hour (rate limiter).
- System prompt states: answer only about this business, never give a lending recommendation, say when
  data is uncertain (reference `uncertain_paise`).
- Conversations stored in `copilot_messages` (id, org_id, conversation_id, role, content, created_at).
