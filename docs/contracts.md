# Contracts

**Status:** living doc · **Scope:** cross-repo shared machinery this repo owns

**Single source of truth for the contracts framework in `docs/`** — the canonical
wire contracts (`contracts/`), the codegen pipeline (`scripts/gen_*.py`), the shared
libs (`libs/`), the drift guards, and the change rules. Everything here is
**landed**. Absorbs the retired `contracts/README.md`. The thin-client *how-to*
(auth flow, SSE resumption, retry policy) is
[`contracts-consumer-guide.md`](contracts-consumer-guide.md) — a different audience,
not restated here.

One constraint governs everything: consumers span **private/proprietary** repos
(`ludo-gateway`, `ludo-webapps`) and **public/BSL** repos (`ludo-cli`,
`ludo-desktop`) — so every vendored artifact must stay **publishable**: no secrets,
no engine internals, no broker constants in client-safe outputs.

---

## 1. The contract set (`contracts/`)

| Contract | File | Between | Notes |
|---|---|---|---|
| **A — control-plane** | `contract_a.openapi.yaml` | gateway ↔ clients | migrations, events, accounts, desktop PKCE auth, estimate scope. REST + **SSE**. Generate typed clients from it. |
| **B — agent events** | `session-event.schema.json` | agent → gateway (broker, `ludo.events.<session_id>`) | event envelope v2: `type` · `payload` · `at` · `session_id` · `schema_version` · `checkpoint_required`. |
| **B — job message** | `job-message.schema.json` | gateway → agent (broker, `ludo.jobs`) | the job-submit half of the agent seam. |
| **C — billing/commerce** | `contract_c.openapi.yaml` | gateway ↔ clients | payments, subscriptions, invoices, discounts, referrals, estimates. **Separate** so commerce can split out later with zero client churn. |
| **shared types** | `shared-types.yaml` | A + C | `Account`, `account_id`, `Money` — single source; A and C `$ref` them, never redefine inline. |

**Contract A conventions:** resource paths are `/api/v1/*`; operational
(`/healthz`, `/system/status`) and auth (`/auth/desktop/*`) are un-prefixed. The
event stream is **SSE** framed `id:`/`event:`/`data:` — clients parse SSE, **not
NDJSON**. The shared codec is `libs/python/ludo_shared/sse.py` (§4).

## 2. Authorship vs canonical

The schema files under `contracts/` are the **published canonical**. Authorship
sits with the emitting component, which must stay in sync with the published file:

- **A / C** — authored by the **gateway** (it serves these surfaces).
- **B events** — the envelope the **agent** emits. The `type` vocabulary (12):
  `session_started` · `session_end` · `model_started` · `model_completed` ·
  `job_started` · `job_completed` · `job_failed` · `turn_started` ·
  `turn_completed` · `safety_event` · `checkpoint_requested` · `verify_stage`
  (per-rung verification progress, added 2026-07-15). The schema enum is
  canonical; the kernel's native event types (`agentix/event_types.py` +
  `events.py`) are enforced against `session-event.schema.json` by the CI gate
  `tests/unit/test_event_contract_drift.py` — the kernel never imports the
  generated package to stay brand-free.
- **B jobs** — the payload the **gateway** publishes; mirror of the agent worker's
  `JobMessage`.

**A contract change = edit `contracts/` first, then the emitter, then re-vendor
the consumers.**

## 3. Consumers + vendoring

Every consumer **vendors** (keeps a byte-identical copy); none edits its own copy:

- `ludo-gateway/contracts/` — A, C, shared-types, both B schemas.
- `ludo-cli/contracts/` — A (as `openapi.yaml`), shared-types, both B schemas.
- `ludo-webapps/backend/contract/` — Contract B (`session-event.schema.json`).
- `ludo-desktop` — hand-codes Swift DTOs from the spec; reconciled at review, not
  byte-vendored.

## 4. Codegen (`scripts/gen_*.py`)

Three sibling generators, one source of truth: `contracts/*.schema.json` (the wire
enums/types) + `constants/cluster.yaml` (broker subjects/streams, migration
lifecycle). **Re-run after any contract or cluster.yaml change.**

- `gen_shared.py` → `libs/python/ludo_shared/_generated.py` — the Python wire
  types + broker constants the Python repos stop hand-maintaining.
- `gen_ts.py` → `libs/ts/ludo_shared/generated.{js,d.ts}` — dependency-free ESM
  for the frontends. **Client-safe: enums + lifecycle labels only, NO broker/NATS
  constants** (public clients never touch the broker).
- `gen_swift.py` → `libs/swift/LudoShared/Generated.swift` — same client-safety
  rule; the desktop repo vendors the file into its SwiftPM target.

## 5. Shared libs (`libs/`)

- **`libs/python/ludo_shared/`** — client-safe shared package: the generated wire
  types plus the hand-written **SSE codec** (`sse.py` — one canonical
  encode/decode of the Contract A frame; the gateway encodes, thin clients
  decode). Vendored by agent, gateway, cli, webapps.
- **`libs/internal/ludo_internal/`** — **INTERNAL-ONLY** shared NATS transport.
  Vendored **only** by the private repos (`ludo-agent`, `ludo-gateway`); the
  public clients must **never** vendor it — the guard's vendor list deliberately
  omits them.
- `libs/ts/`, `libs/swift/` — the generated client-safe modules (§4).
- The kernel wheel ships `src/agentix` only — `libs/` is vendoring machinery,
  never a kernel dependency (`docs/seams.md`).

## 6. Drift guards (`scripts/check_*.py`, run from `agentix/`)

| Guard | Checks |
|---|---|
| `check_contract_drift.py` | every consumer's vendored `contracts/` copy is byte-identical to canonical; a sibling repo not checked out is skipped, not failed |
| `check_shared_drift.py` | (1) vendored `ludo_shared` copies byte-identical per language; (2) **freshness** — re-running the generators changes nothing, i.e. canonical artifacts were regenerated after the last contract/cluster edit |
| `check_internal_drift.py` | `ludo_internal` byte-identical in agent + gateway only |
| `check_config_drift.py` | vendored `constants/cluster.yaml` copies byte-identical (the sibling guard) |

Plus the kernel-side gate `tests/unit/test_event_contract_drift.py` (§2).

## 7. Change rules

- **A / C** (client-facing): evolve **additively**; a breaking change means a
  version bump + deprecation window + regenerated typed clients. The contract PR
  lands **before** clients adapt.
- **B** (agent ↔ gateway): a coordinated cross-repo change; breaking →
  `schema_version` bump.
- Clients **never** see raw Contract B — the gateway projects a curated client
  event subset.
- Shared types live in `shared-types.yaml` and are `$ref`'d — `Account`/`Money`
  are never redefined inline.
