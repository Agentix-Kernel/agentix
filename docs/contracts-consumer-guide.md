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

## Auth — browser-redirect GitHub OAuth + PKCE (S256)

The gateway brokers GitHub OAuth so the client never holds an OAuth client secret. The client
proves it started the flow with **PKCE** (`S256`) — no secret needed for a native/public client.
Worked reference: `ludo-desktop` `AuthService.swift`.

1. **Generate a `code_verifier`** — 43–128 chars of cryptographically-random URL-safe text.
   Keep it on the device only; it never leaves.
2. **Derive the `code_challenge`** — `BASE64URL(SHA256(code_verifier))`, no padding.
3. **Start** — open the system browser at
   `GET /auth/desktop/start?redirect_uri=<scheme>://auth/callback&code_challenge=…&code_challenge_method=S256&state=<csrf>`.
   The gateway runs the GitHub leg, then 302-redirects back to `redirect_uri`.
4. **Catch the callback** — your custom scheme (`ludo-desktop://auth/callback`) or a loopback
   `http://127.0.0.1:<port>/callback`. Verify `state` matches what you sent.
5. **Exchange** — `POST /auth/desktop/token` with `{ "code": …, "code_verifier": … }`. The
   gateway recomputes `SHA256(code_verifier)`, checks it equals the stored `code_challenge`, and
   returns `{ "token": <bearer>, "account_id": … }`.
6. **Store the bearer** in the platform secret store (see below) and send it as
   `Authorization: Bearer <token>` on every Contract A call.

> DEV gateways stub the GitHub leg (synthetic code, dev JWT); STAG/PROD perform the real
> exchange. The client flow is identical against either.

## Client-config convention

Resolve, in order: **explicit override → platform store → `cluster.yaml` stage default**. Never
hardcode a deployment URL in client source.

| Concern | Convention |
|---|---|
| Base URL | env `LUDO_API_URL` (or a platform setting). Default = `constants/cluster.yaml` `domains.<stage>` — dev `http://10.0.99.1:8080`, prod `https://runludo.com`. Address infra by the loopback alias, never `localhost`. |
| Bearer token | env `LUDO_API_TOKEN` for headless/CLI; the OS secret store for GUI clients (Keychain / Windows Credential Manager / libsecret). The `code_verifier` is transient and never stored. |
| Stage | `APP_ENV` ∈ `dev` · `stag` · `prod` selects which `domains.<stage>` block to read. |

**Token-storage tiers** (most→least secure; pick the most secure the platform offers):
OS secret store (Keychain/Credential Manager) → encrypted app config → process env var
(`LUDO_API_TOKEN`, for CI/headless). Never write tokens to logs or plaintext dotfiles in `$HOME`.

## SSE — live events, resumption, reconnect

`GET /api/v1/migrations/{id}/events` streams **Contract B** as SSE frames (`id:`/`event:`/`data:`,
**not** NDJSON). The shared `decode_sse` codec (`ludo_shared`) turns the byte stream into
`(seq, type, payload)`.

- **`id:` is the JetStream sequence** — persist the last one seen. On reconnect, send it as the
  `Last-Event-ID` request header; the gateway replays only events after it (at-least-once, so
  dedupe by `seq`).
- **Reconcile, then resume.** After any disconnect: `GET /api/v1/migrations/{id}` to snapshot
  current state (`state_index`, `agent_outcome`, cost), *then* reopen the stream from
  `Last-Event-ID`. This closes the gap between the last seen event and now.
- **Auto-reconnect with backoff** (see below). The stream ends on `session_end`.

## Retry / backoff

Wrap every request and the SSE reopen in a bounded retry with **exponential backoff + jitter**.

- **Retry only transient failures**: connection/timeout errors, `429`, and `5xx`. Never retry
  `4xx` other than `429` (they won't get better on replay).
- **Backoff**: `delay = min(cap, base * 2**attempt) + random_jitter` (e.g. `base=0.5s`,
  `cap=30s`), with a max-attempt ceiling. Honor a `Retry-After` header when present.
- **Idempotency**: enqueue endpoints (`approve`/`resume`, `202`) take an `Idempotency-Key` —
  reuse the *same* key across retries of the same logical action so a replay can't double-submit.
  Pure reads (`GET`) are naturally safe to retry.

## Error taxonomy (Contract A)

| Status | Meaning | Client behavior |
|---|---|---|
| `400 / 422` | Malformed request / failed validation | Fix the request; do **not** retry as-is. |
| `401` | Missing/invalid/expired bearer | Re-run the auth flow; refresh the token. |
| `403` | Authenticated but not authorized — e.g. `account required` (no account bound to the caller, CRIE 002 #31) | Surface as a permissions issue; do not re-auth blindly. |
| `404` | Not found **or** out of tenant scope (intentionally indistinguishable) | Treat as "not yours / gone". |
| `409` | Conflict (e.g. duplicate idempotent submit) | Reconcile state via `GET`; usually already-applied. |
| `429` | Rate limited | Back off (honor `Retry-After`), then retry. |
| `5xx` | Gateway/broker transient | Retry with backoff; reconcile after. |
| `501` | Endpoint not yet wired on this stage (e.g. real OAuth on DEV vs STAG/PROD) | Treat as unavailable, not a bug. |
