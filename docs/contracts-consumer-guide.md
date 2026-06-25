# Contract A — thin-client consumer guide

How any **thin client** (desktop, CLI, mobile, web) consumes the gateway's **Contract A**
(REST + SSE). Client-agnostic; generalized from `ludo-desktop/MacOS/prd_macos.md` §3/5/7.
The canonical schema is [`../contracts/contract_a.openapi.yaml`](../contracts/contract_a.openapi.yaml)
— generate or hand-write typed DTOs **from it**, never from a sibling client's copy.

A client is a **thin** client: no migration logic, no MinIO/agent/broker access, no customer PII
beyond the creds the user types for their own Odoo. Everything flows through the gateway (Contract A).

## Client building blocks (any stack)
| Concern | Approach |
|---|---|
| Networking | async HTTP; typed models **aligned to Contract A** (`URLSession`/`httpx`/fetch — stack's choice). |
| Live events | **SSE** over a byte/line stream; parse frames `id:`/`event:`/`data:` (**not** NDJSON); auto-reconnect with backoff. |
| Auth | browser-redirect GitHub OAuth + **PKCE**; bearer token stored in the platform secret store (Keychain / credential manager / env). The `code_verifier` never leaves the device. |
| Reconcile | on SSE reconnect, `GET /migrations/{id}` first to reconcile state, then resume the stream from `Last-Event-ID`. |

## Endpoints (Contract A surface)
Resource paths are `/api/v1/*`; operational (`/healthz`, `/system/status`) and auth
(`/auth/desktop/*`) are un-prefixed. Authoritative list: the OpenAPI artifact.

| Purpose | Method · path | Notes |
|---|---|---|
| Desktop auth start | `GET /auth/desktop/start?redirect_uri=…&code_challenge=…` | opens in browser; gateway brokers GitHub OAuth |
| Auth callback | redirect → `<scheme>://auth/callback?code=…` | client catches via its custom scheme / loopback |
| Token exchange | `POST /auth/desktop/token` `{code, code_verifier}` | PKCE; returns bearer token |
| Accounts | `GET /api/v1/accounts` | account picker (scoped by role) |
| Estimate / X-Ray | `POST /api/v1/estimates`, `GET /api/v1/estimates/{id}` | read-only scan → inventory |
| Inventory | `GET /api/v1/estimates/{id}/inventory` | modules, module→models, counts, custom_fields, port_blockers |
| Resolve scope | `POST /api/v1/estimates/{id}/resolve-scope` | `{selected_modules, selected_models, excluded_custom_fields}` → resolved closure |
| List / get migrations | `GET /api/v1/migrations` · `GET /api/v1/migrations/{id}` | tenancy-scoped; `state_index`, `agent_outcome`, cost |
| Approve / resume | `PATCH /api/v1/migrations/{id}/approve` · `…/resume` | enqueue-and-ack (202); Idempotency-Key |
| Live events | `GET /api/v1/migrations/{id}/events` (SSE) | curated Contract B (model/job/turn/safety/session_end) |

> Some rows (e.g. `/me`, `/connections`, full estimate-scope handlers) are still landing in the
> gateway (B2/#94). Treat the OpenAPI file as the source of truth; a missing endpoint = not yet wired.

## Scope-selection client rules (epic #94)
- **Default = everything (opt-out).** Empty selection ⇒ migrate all discovered models.
- **Granularity = module → model + custom-fields-only.** Standard fields always migrate; only
  custom/Studio fields are individually de-selectable.
- **Dependencies auto-include + show.** The client never computes closure — it sends the tentative
  selection to `/resolve-scope` and renders `auto_included_deps` + `port_blockers_hit`.
- **System models** are surfaced read-only as `excluded_system_models` (cannot be forced in).
- Selection persists on the Migration (`selected_modules`, `selected_models`,
  `excluded_custom_fields`) — never recomputed client-side at launch.
