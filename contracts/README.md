# Contracts — canonical cross-repo seams

**This directory is the single source of truth for the LUDO cluster contracts.**
Every consumer repo **vendors** (keeps a byte-identical copy) from here; none edits its
own copy. Drift is guarded by [`../scripts/check_contract_drift.py`](../scripts/check_contract_drift.py).
Consumers span **private/proprietary** repos (`ludo-gateway`, `ludo-webapps`) and **public/BSL**
repos (`ludo-cli`, `ludo-desktop`) — so every vendored contract artifact must stay publishable
(no secrets, no engine internals). See [`../docs/licensing-policy.md`](../docs/licensing-policy.md).

| Contract | File | Between | Notes |
|---|---|---|---|
| **A — control-plane** | [`contract_a.openapi.yaml`](contract_a.openapi.yaml) | gateway ↔ clients (WMD) | migrations, events, accounts, desktop PKCE auth, estimate scope. REST + **SSE** (`text/event-stream`, not NDJSON). Generate typed clients from it. |
| **B — agent events** | [`session-event.schema.json`](session-event.schema.json) | agent → gateway (NATS `ludo.events.<session_id>`) | event envelope v2 (`type` · `payload` · `at` · `session_id` · `schema_version` · `checkpoint_required`). |
| **B — job message** | [`job-message.schema.json`](job-message.schema.json) | gateway → agent (NATS `ludo.jobs`) | the job-submit half of the agent seam. |
| **C — billing/commerce** | [`contract_c.openapi.yaml`](contract_c.openapi.yaml) | gateway ↔ clients | payments, subscriptions, invoices, discounts, referrals, rollup, estimates. **Separate** so commerce can split out later with zero client churn. |
| **shared types** | [`shared-types.yaml`](shared-types.yaml) | A + C | `Account`, `account_id`, `Money` — single source, no drift. |

**Contract A conventions:** resource paths are `/api/v1/*`; operational (`/healthz`,
`/system/status`) + auth (`/auth/desktop/*`) are un-prefixed. The event stream is **SSE**
framed `id:`/`event:`/`data:` — clients parse SSE, not NDJSON.

## Authorship vs canonical
The schema files here are the **published canonical**. Authorship still sits with the
emitting component, which must stay in sync with the published file:
- **A / C** — authored by `ludo-gateway` (it serves these surfaces).
- **B events** — the envelope the **agent** emits (`ludo-agent/src/ludo/events.py` +
  `event_types.py`); the agent's runtime types must validate against `session-event.schema.json`.
- **B jobs** — the payload the **gateway** publishes; mirror of `ludo-agent/src/ludo/worker/payload.py::JobMessage`.

A contract change = edit **here** first, then the emitter, then re-vendor the consumers.

## Consumers (vendor from here — do not edit their copies)
- `ludo-gateway/contracts/` — A, C, shared-types, both B schemas.
- `ludo-cli/contracts/` — A (as `openapi.yaml`), shared-types, both B schemas.
- `ludo-webapps/backend/contract/` — Contract B (`session-event.schema.json`).
- `ludo-desktop` — hand-codes Swift DTOs from the spec (reconciled at review, not byte-vendored).

Run `python scripts/check_contract_drift.py` (from the repo root) to verify all copies are in sync.

## Change rules
- **A / C** (client-facing): evolve **additively**; breaking change → version bump + deprecation
  window; regenerate typed clients. The contract PR lands **before** clients adapt.
- **B** (agent↔gateway): coordinated cross-repo change; breaking → `schema_version` bump.
- Clients **never** see raw Contract B; the gateway projects a curated client event subset.
- Keep shared types in `shared-types.yaml`; A and C `$ref` them — never redefine `Account`/`Money` inline.
