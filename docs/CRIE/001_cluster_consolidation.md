# CRIE 001 — cluster-wide consolidation into ludo-init

Date: 2026-06-25. Scope: all 6 repos (`ludo-agent`, `ludo-gateway`, `ludo-webapps`,
`ludo-cli`, `ludo-desktop`, `ludo-init`). Goal: find Conflicts, Redundancies,
Integration-Efficiencies (CRIE) and consolidate common code into the `ludo-init` hub.

## Frame: license + visibility (governs what may move to the hub)

Target model (owner decision, 2026-06-25): the proprietary perimeter is the engine + edge +
frontends; only the two public client repos are BSL.

| Repo | License (target) | Visibility | On-disk LICENSE today |
|---|---|---|---|
| ludo-agent | **Proprietary** | private | BSL 1.1 — **needs flip** (C-1) |
| ludo-gateway | **Proprietary** | private | BSL 1.1 — **needs flip** (C-1) |
| ludo-webapps | **Proprietary** | private | Proprietary ✓ |
| ludo-cli | BSL 1.1 | **public** | BSL 1.1 ✓ |
| ludo-desktop | BSL 1.1 | **public** | BSL 1.1 ✓ |
| ludo-init (hub) | BSL 1.1 | private | BSL 1.1 ✓ |

**Hub rule (the constraint that drives every recommendation below):** `ludo-cli` and
`ludo-desktop` are *public* and **vendor selected files from `ludo-init`**. Therefore any hub
file a public repo vendors is effectively public. The hub itself is private and proprietary
code lives in the private repos — so the hub may hold only **publishable** material:
client-facing contracts, *client-side* transport (e.g. SSE decode), generic helpers, docs.
**Internal-only** shared code (broker/NATS client, job-message types, SSE encode) is shared
**only between the private repos** (`ludo-agent` ⇄ `ludo-gateway`) and must never be vendored
into the public clients. Engine internals, secrets logic, ORM schemas, product copy: never in
the hub.

## Baseline — already consolidated (no action; acknowledge)

Strong contract-first hygiene is already in place (commit `344a2ca`):
- `contracts/` — A/C OpenAPI + B schemas (`session-event`, `job-message`) + `shared-types`,
  byte-vendored by gateway/cli/webapps, guarded by `scripts/check_contract_drift.py`.
- `constants/cluster.yaml` — network, ports, broker subjects/streams, locale; vendored by
  agent/gateway/cli, guarded by `scripts/check_config_drift.py`.
- `templates/` (ruff, gitignore, env) + 13 cluster docs + 5 proposals.

The gaps below are what remains.

---

## Conflicts (C)

**C-1 — Licensing: docs/LICENSE drift vs the decided model.** RESOLVED (model) /
PARTIALLY DONE (files). Owner decision 2026-06-25: `ludo-agent`, `ludo-gateway`,
`ludo-webapps` are **proprietary/private**; only `ludo-cli` + `ludo-desktop` are **BSL/public**.
- Done: hub docs aligned — `CLAUDE.md` licensing table, `docs/licensing-policy.md`,
  `contracts/README.md`.
- **Still open (legal files in private repos):** `ludo-agent/LICENSE` + `pyproject.toml`
  (`BUSL-1.1`) and `ludo-gateway/LICENSE` still declare BSL 1.1 — must be flipped to the
  proprietary notice. Held pending owner go-ahead because it reverses an earlier same-day BSL
  decision on `ludo-agent`.

**C-2 — SSE framing: desktop parses the wrong wire format (BUG).** Canonical Contract A is
**SSE** (`id:`/`event:`/`data:` frames; `contracts/README.md`, `contract_a.openapi.yaml`).
`ludo-cli` parses SSE correctly (`src/omg/client.py` `stream_events`). `ludo-desktop`
parses **NDJSON** (one JSON per line) with a stale "NDJSON" comment —
`ludo-desktop/MacOS/app/Sources/LudoDesktop/Services/LiveAPIClient.swift:48-76`. Against the
real gateway stream this will mis-parse. *Fix:* rewrite desktop stream parser to SSE
framing (the shared SSE-parsing reference in IE-3 is the spec).

**C-3 — Locale default contradicts canonical.** `cluster.yaml:57-58` sets
`backend_default: "de"` (DACH + house rule), but `ludo-gateway` `Account.locale` defaults
`"en"` (`backend/app/models.py`), and `ludo-webapps` `resolveLocale` falls back to `en`
(`libs/shared/i18n.js`), with hardcoded `"de"` scattered in webapps backend
(`config.py`, `db.py`). *Fix:* derive locale default from `cluster.yaml`; reconcile en/de.

**C-4 — Client base-URL / config divergence.** `ludo-cli` defaults
`http://10.0.99.1:8080` via `LUDO_API_URL` (`src/omg/config.py`); `ludo-desktop` hardcodes
`https://ludo.euroblaze.de` (`AuthService.swift`). No shared client-config convention.
*Fix:* IE-3 client-config doc + read defaults from `cluster.yaml`.

**C-5 — Contract source-vs-schema drift gap.** `check_contract_drift.py` compares vendored
*copies* to canonical, but nothing checks that the **emitter's runtime types** match the
canonical schema: `ludo-agent` `event_types.py` (11 event types) + `worker/payload.py`
`JobType` (10 values) are hand-kept against `session-event.schema.json` /
`job-message.schema.json`. Silent drift risk. *Fix:* IE-1 (generate the Python types from
the schema) closes this; or extend the drift checker to validate agent source vs schema.

---

## Redundancies (R)

**R-1 — gateway ⇄ webapps backend parallel control-plane (~500 LOC) — INTENTIONAL.**
Both implement config/auth/tenancy/SSE/broker. This is the gated `flywheel#96` cutover;
`ludo-webapps/backend` is *retiring into the gateway*. **Do not lift to the hub** — it
converges into `ludo-gateway`. Track only; resolves at B5 cutover.

**R-2 — NATS subjects/streams hardcoded twice though canonical exists.** `cluster.yaml:24-31`
already defines `broker.subjects` + `broker.streams`, yet both
`ludo-agent/src/ludo/worker/nats.py:23-27` and
`ludo-gateway/backend/app/services/broker.py:18-22` re-hardcode the literals (the latter
even comments "MUST match the agent's nats.py"). *Fix:* read from the vendored
`cluster.yaml`, or from the IE-2 shared transport lib. Small but high-signal.

**R-3 — SSE framing implemented twice in Python.** Gateway *encodes* SSE frames
(`services/projector.py` `sse_stream`); cli *decodes* them (`client.py` `stream_events`).
Same wire format, two hand-rolled impls. *Fix:* one shared encode/decode codec (IE-2).

**R-4 — Three representations of the same contract types.** `ludo-agent` has canonical
Pydantic (`payload.py` `JobMessage`/`JobType`, `events.py` `SessionEvent`); `ludo-gateway`
re-derives the concepts; `ludo-cli` uses untyped `dict[str, Any]`. *Fix:* IE-1 generated
package gives all three the same models.

**R-5 — webapps-internal duplication (already logged in `ludo-webapps/docs/CRIE` #41-56).**
`MIGRATION_STATES` (py+js), `utc_now()` ×7, email validator ×2, `_ROLES` ×5, `_serialize`
×7. Mostly repo-local. **Hub-relevant subset:** `MIGRATION_STATES` is a *cross-language
enum* duplicated py↔js — it should derive from a canonical source (IE-5).

---

## Integration efficiencies (IE) — consolidate into ludo-init

**IE-1 (P0) — Generate types from the contracts; stop hand-writing them.** The schemas are
the SoT; make code a build artifact. Add a `ludo-contracts` Python package in the hub:
Pydantic v2 models + enums generated from `job-message.schema.json` + `session-event.schema.json`
(+ `JobType`/event-type enums), consumed by agent, gateway, cli. Add TS type generation from
`contract_a/c.openapi.yaml` for webapps; Swift DTO generation/sync for desktop. *Removes
R-4 and C-5; kills an entire drift class.* Publishable (contract types only → safe for
public cli). Est. dedup: ~3 hand-kept copies + ongoing sync cost.

**IE-2 (P0) — Shared Python transport, split by visibility.** Two homes, because consumers
straddle the public/private line:
- *Client-safe* (hub, vendored by public cli + private gateway): the **SSE decode** codec
  (R-3) — turns the `id:`/`event:`/`data:` byte stream into `(seq, type, payload)`. ~30 LOC.
- *Internal-only* (shared **only** between private `ludo-agent` ⇄ `ludo-gateway`, never the
  public clients): the dual-mode NATS `Broker` client (~141 LOC, from
  `ludo-gateway/.../services/broker.py`), the SSE **encode** side, and the subjects/streams
  constants (R-2, sourced from `cluster.yaml`). Place under a hub path the public clients do
  **not** vendor (e.g. `libs/internal/`), or in one of the private repos as canonical.
Est. dedup: ~200-250 LOC + the two manual-sync points. The split is what keeps NATS internals
out of the public BSL repos.

**IE-3 (P1) — Client know-how docs into `docs/`.** Language-bound clients can't share code,
but can share specs. Consolidate (extending `docs/contracts-consumer-guide.md`): PKCE flow
reference (from `ludo-desktop` `AuthService.swift`), SSE-parsing reference (the C-2 fix
spec), retry/backoff strategy, client-config conventions (env names, base-URL from
`cluster.yaml`, token-storage tiers), and a client error taxonomy. Serves future
Windows/mobile/WMD clients. Resolves C-4; supplies the C-2 spec.

**IE-4 (P1, gated by C-1) — Generic Python infra base.** 12-factor config loader +
prod-secret guard, JWT/Bearer auth + `CurrentUser`, transient-error classification — shared
by agent+gateway(+cli). Modest savings; only worthwhile if it doesn't entangle proprietary
`ludo-webapps`. Defer behind IE-1/IE-2.

**IE-5 (P2) — Cross-language enum emission.** Emit `MIGRATION_STATES`, `JobType`, event
types, pricing/combo constants from one canonical source (`cluster.yaml` or contracts) into
per-language artifacts (py/js/swift). Removes the R-5 cross-language subset.

**IE-6 (P2) — Extend drift guardrails.** Have `check_contract_drift.py` also validate
emitter source enums against canonical schemas (closes C-5 if IE-1 not done), and add a
codegen-freshness check so generated artifacts can't go stale.

---

## Guardrails — must NOT move to the hub (public-vendoring boundary)

- **ludo-agent:** tools (~37, ~19.7K LOC), dispatcher/actions, memory, Cortex/LLM
  providers, storage schemas, spike harness, cost/estimate rendering. Engine internals.
- **ludo-gateway:** ORM models (`models*.py`), routers, app factory, DB setup. Gateway-specific.
- **ludo-webapps:** app pages, brand theme, translation *content* (product copy). Also
  proprietary per C-1.

## Prioritized roadmap

| ID | Action | Priority | Status | Touches |
|---|---|---|---|---|
| C-1 | Resolve licensing | P0 | **docs done**; agent/gateway LICENSE flip pending owner go | hub docs (+ private repos) |
| C-2 | Fix desktop SSE parser | P0 | **done** | ludo-desktop |
| IE-1 | Generated contract types | P0 | **hub done + verified**; consumer vendor pending | hub → agent/gateway/cli |
| IE-2 | SSE codec + broker constants | P0 | **hub done (codec+constants)**; broker move + vendor pending | hub → agent/gateway/cli |
| R-2 | Subjects/streams from cluster.yaml | P1 | **canonical in hub** (`ludo_shared`); repoint pending | agent, gateway |
| R-3/R-4 | one SSE codec / one type set | P1 | **canonical in hub**; repoint pending | agent, gateway, cli |
| C-3 | Locale default from cluster.yaml | P1 | open | gateway, webapps |
| IE-3 | Client know-how docs | P1 | open | hub |
| C-4 | Client config convention | P1 | open | hub + cli/desktop |
| IE-5/6 | Enum emission, drift guards | P2 | **IE-6 partly** (`check_shared_drift.py`) | various |

R-1 is intentional (cutover) — no action.

## Realized (this pass, 2026-06-25)

Hub-side consolidation built + verified in `ludo-init`:
- `scripts/gen_shared.py` — emits `libs/python/ludo_shared/_generated.py` from
  `contracts/*.schema.json` + `constants/cluster.yaml` (10 JobType + 11 EventType + broker
  constants + `JobMessage`/`SessionEvent` pydantic). Closes the C-5 source-vs-schema gap.
- `libs/python/ludo_shared/sse.py` — the single SSE encode/decode codec (R-3).
- `scripts/check_shared_drift.py` — guards vendored copies (mirrors the contract/config guards).
- Verified: generated enums == schema enums; constants == cluster.yaml; `JobMessage` forbids
  extra; `SessionEvent` allows extra; SSE encode→decode round-trips.
- C-1 docs aligned (`CLAUDE.md`, `licensing-policy.md`, `contracts/README.md`).
- C-2: `ludo-desktop` `LiveAPIClient.swift` now parses SSE frames (was NDJSON) + sends
  `Last-Event-ID` on reconnect.

**Remaining (consumer integration — per-repo, run each repo's tests):** vendor `ludo_shared`
into `ludo-agent`/`ludo-gateway`/`ludo-cli` under `<repo>/libs/ludo_shared/` and repoint
imports (agent `worker/nats.py` constants + `payload.py` `JobType`; gateway
`services/broker.py` constants + projector `sse_stream`; cli `client.py` `stream_events` →
`decode_sse`); move the internal NATS `Broker` client to the private-only shared home (IE-2).
Record realized LOC savings here as each lands.
