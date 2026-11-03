# API spec (`/v1`)

JSON everywhere. Money fields are integers ending in `_paise`. Dates are ISO 8601. List endpoints take
`?cursor=<opaque>&limit=<1..100, default 50>` and return `{"items": [...], "next_cursor": str|null}`.
Errors are RFC 9457 `application/problem+json`: `{type, title, status, detail, instance, request_id}`.
Cross-tenant access returns **404**, not 403, so ids can't be probed.

## Auth
| Method | Path | Role | Body → Response |
| --- | --- | --- | --- |
| POST | /v1/auth/login | — | `{email, password}` → `{access_token, expires_in}` + refresh cookie |
| POST | /v1/auth/refresh | cookie | → new access token, rotated cookie |
| POST | /v1/auth/logout | any | revokes refresh family → 204 |
| GET | /v1/me | any | `{id, email, role, org_id}` |
| POST | /v1/users | admin | `{email, password, role}` → user |

## Businesses and accounts
| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| POST | /v1/businesses | owner, admin | `{name, category}` |
| GET | /v1/businesses | any | owners see their own; officers/admins see the org |
| GET | /v1/businesses/{id} | any (scoped) | includes account list and latest metric run id |
| POST | /v1/businesses/{id}/accounts | owner | `{bank, format, account_number, type, upi_id?}`; server stores last 4 only |
| GET | /v1/parsers | any | supported `(bank, format)` pairs from the registry |

## Uploads
| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| POST | /v1/accounts/{id}/uploads | owner | multipart `file`; header `Idempotency-Key` (required, UUID); 201 new, 200 duplicate, 409 key reuse with different body, 413 too large, 415 wrong type |
| GET | /v1/uploads/{id} | owner, officer | `{status, stages:[{stage,status,attempts,error}], recon:{reason, break_line, expected_paise, actual_paise}|null}` |
| GET | /v1/businesses/{id}/uploads | any (scoped) | list |

## Ledger and evidence
| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| GET | /v1/businesses/{id}/transactions | any (scoped) | filters `from, to, account_id, label, evidence_level, direction` |
| PATCH | /v1/transactions/{id}/label | officer | `{label, note}` → appends a human label |
| GET | /v1/businesses/{id}/metrics | any (scoped) | `{run_id, months:[{month, gross_inflow_paise, net_business_inflow_paise, uncertain_paise, outflow_paise, obligations_paise, closing_balance_paise, volatility_bp}]}` |
| GET | /v1/businesses/{id}/graph | officer | `{nodes:[{id,label,kind}], edges:[{from,to,total_paise,txn_ids}], window:{from,to}}`; `?from=&to=` |
| GET | /v1/businesses/{id}/evidence | officer | evidence links of the current run |
| GET | /v1/flags | officer | `?status=open&kind=` org review queue |
| GET | /v1/flags/{id} | officer | flag + evidence transactions |
| PATCH | /v1/flags/{id} | officer | `{status: confirmed|dismissed, note}` (note required) |

## Assessments
| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| POST | /v1/businesses/{id}/assessments | officer | creates draft, snapshots current metric run id |
| GET | /v1/assessments/{id} | officer | |
| POST | /v1/assessments/{id}/transitions | officer | `{to, note}`; illegal → 409 |

## Copilot
| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| POST | /v1/businesses/{id}/copilot | officer | `{question, conversation_id?}` → `{answer, citations:[{type: txn|metric, id}], conversation_id}` |

## Admin and ops
| Method | Path | Role | Notes |
| --- | --- | --- | --- |
| GET | /v1/admin/dead-letters | admin | dead pipeline runs |
| POST | /v1/admin/dead-letters/{run_id}/retry | admin | requeues that stage |
| GET | /v1/admin/audit | admin | filter by entity, actor, date |
| GET | /healthz, /readyz, /metrics | — | not versioned |
