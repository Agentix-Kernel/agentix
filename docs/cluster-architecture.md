# LUDO — Cluster architecture (cross-repo)

The detailed cross-repo topology + contracts that span the whole LUDO cluster. This is the
companion to the hub **[`../CLAUDE.md`](../CLAUDE.md)** (which owns the shared vocabulary +
the one-screen topology) and to **[`../contracts/`](../contracts/)** (the canonical seams).
Each component repo keeps only its *internal* architecture: agent internals →
`ludo-agent/arch.md` §2–8; gateway cutover/prod ops → `ludo-gateway/docs/design.md` §5–8.

Consolidated from `ludo-gateway/docs/design.md` §1–4 and `ludo-agent/arch.md` §1 (topology +
the Contract B seam). Engine *doctrine* (locked decisions, the four flywheels, autonomy bar)
stays agent-owned in `ludo-agent/CLAUDE.md` + `arch.md` — referenced, not duplicated here.

## 1. Why a single control-plane edge
The **gateway** is the single client-agnostic control-plane edge in front of the broker for all
clients (web / mobile / desktop = **WMD**). It **absorbs the apps backend** (the former
`ludo-webapps` FastAPI BFF) — both the **comms** half (auth, tenancy, vault, migrations, the
event relay) and the **commerce** half (payments, discounts, referrals, billing, subscriptions,
calculator, estimates, support). After cutover, **`ludo-webapps` = the Vue frontends only**;
the agent stays an internal worker/engine. (The apps backend is the *donor* in this strangler-fig
transplant — see `ludo-gateway/docs/design.md` §5.)

**Cluster locked decisions**
- **One backend now** (comms + commerce in the gateway) → no split-brain. *Future:* peel commerce
  into its own secure-DB service when volume demands (Contract C pre-draws the seam).
- **Closed-source / BSL** — design as if source could leak (secrets in KMS, sound authz; BSL ≠ obscurity).
- The **broker is the only seam** to the agent. Clients never touch NATS; the agent has no public
  ingress and no PII (only the opaque `account_id`).

## 2. Topology — broker-mediated, never direct calls
```
 Web ─┐
 Mobile ─┤── HTTPS (Contract A REST + SSE) ──▶  GATEWAY (public zone, 1 writer + read replicas)
 Desktop ─┤                                      auth · tenancy · vault · migrations · commerce
 cli ─────┘                                          │ enqueue job (Contract B)   ▲ subscribe+replay
        push (APNs/FCM, mobile)                       ▼                            │
                                              ┌──────── NATS JetStream ───────────┐
                                              └───────────────┬───────────────────┘
                                                              ▼ consume/ack/publish
                                                        AGENT worker (private zone — no ingress, no PII)
```
**Two zones.** *Public:* the gateway (single writer + stateless read replicas behind TLS/WAF/rate-limit).
*Private:* NATS + the agent, with a `NetworkPolicy` denying public→broker/agent. Job submission and
event delivery go through the **broker, not HTTP**; the gateway is the only component that talks to NATS.

## 3. Interaction patterns (→ transports)
| Need | Transport | Semantics |
|---|---|---|
| **Command** (submit/approve/resume/cancel) | HTTP → **202 + id** | enqueue-and-ack: the *result* arrives on the event stream, not the response. Idempotency-Key → JetStream dedup. |
| **Query** (list/get migrations, inventory, fleet, billing) | HTTP `GET` | DB-resolved, tenancy-scoped. |
| **Live progress** | **SSE** (`text/event-stream`) | **resumable** off the durable JetStream log (Last-Event-ID = stream seq → replay on reconnect). |

## 4. Contracts (the seams) — canonical in [`../contracts/`](../contracts/)
- **A — control-plane** (`contract_a.openapi.yaml`): migrations, events, accounts, desktop PKCE
  auth, estimate scope. gateway ↔ clients. REST + SSE.
- **B — agent seam** (NATS), two halves: `session-event.schema.json` (agent→gateway events on
  `ludo.events.<session_id>`; v2 `type`/`schema_version`/`checkpoint_required`) + `job-message.schema.json`
  (gateway→agent jobs on `ludo.jobs`; mirror of the agent's `JobMessage`). Streams `LUDO_EVENTS` /
  `LUDO_JOBS`. Clients never see raw Contract B — the gateway projects a curated SSE subset.
- **C — billing/commerce** (`contract_c.openapi.yaml`): payments, subscriptions, invoices, discounts,
  referrals, rollup, estimates. **Separate** so commerce can split out later with zero client churn.
- **shared types** (`shared-types.yaml`): `Account`, `account_id`, `Money` — referenced by A + C.

See [`../contracts/README.md`](../contracts/README.md) for authorship, the vendor model, and change rules.
The execution-model + identity + event vocabulary these contracts use are defined once in the hub
[`../CLAUDE.md`](../CLAUDE.md) § Shared vocabulary.
