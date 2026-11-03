# Frontend spec (`frontend/`, milestone M10)

Next.js 15 App Router, TypeScript strict, Tailwind, TanStack Query for server state, Recharts for
charts, Cytoscape.js (or React Flow) for the evidence graph, Playwright for smoke tests.
API types generated from FastAPI's OpenAPI with `openapi-typescript`; no hand-written API types.

## Auth
Access token in memory only (never localStorage). Refresh via the httpOnly cookie on 401, once, then
redirect to `/login`. Route groups `(owner)` and `(officer)` guard by role.

## Pages
| Route | Role | Contents |
| --- | --- | --- |
| /login | — | email + password |
| /businesses | any | list; owners see their own |
| /businesses/[id] | any | overview: monthly chart (net business inflow line, uncertain band above it, gross as faint bars), latest uploads with status, open flags count |
| /businesses/[id]/upload | owner | pick account, drag-drop file, live stage progress (poll `GET /uploads/{id}` every 2 s), reconciliation break shown with the exact line |
| /businesses/[id]/transactions | any | virtualised table, filters, evidence-level chips, officer can relabel |
| /businesses/[id]/evidence | officer | graph view for a chosen 30-day window; clicking an edge lists its transactions; cycles highlighted |
| /flags | officer | review queue sorted by total amount; detail drawer with evidence rows; confirm/dismiss with required note |
| /businesses/[id]/assessment | officer | state, history, transition buttons allowed by the state machine only |
| copilot panel | officer | side panel on business pages; citations render as links that scroll to the transaction or month |
| /admin | admin | dead letters with retry, audit log search |

## Rules
- Money arrives as paise; format once with `Intl.NumberFormat('en-IN', {style:'currency', currency:'INR'})`.
- Every amount on screen that came from evidence shows its level (verified/inferred/unresolved) on hover.
- Empty, loading and error states for every page. Keyboard accessible. No component library lock-in
  beyond Tailwind + a few headless primitives.
