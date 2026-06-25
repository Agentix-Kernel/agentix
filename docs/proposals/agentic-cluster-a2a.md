# The activatable multi-agent cluster — A2A, isolation, guardrails

> **STATUS: DIRECTION — converged design, not the code today.** Cluster-wide
> architecture for running multiple agents across `ludo-*` safely. Companion to the
> migration agent's brain redesign ([competence model, #468](https://github.com/euroblaze/ludo/issues/468))
> and the [Tools topic index (#487)](https://github.com/euroblaze/ludo/issues/487).
> Cross-cluster vocabulary lives in the workspace-root `CLAUDE.md`. **No MCP** in
> scope (deliberately dropped); A2A + LLM tool-calling + isolation + guardrails only.

## Thesis

**Software agents taking autonomous actions inside strictly controlled guardrails** —
across the cluster, to bring operational excellence to customers, users, operators and
admins, **while the codebase shrinks, not grows.**

## Four locked principles

### 1. Agents are an *activatable layer* (key-gated)
A component's agent-nature lights up when a valid LLM key is present; with no key it
runs as **deterministic software**. This generalises "deterministic body, Cortex on
surprise" to the whole cluster. Multiple agents per repo, evolving in functionality,
type and cardinality. **Activation = subscription presence** (see §3).

### 2. Whoever holds the key owns the guardrails
You cannot impose LUDO guardrails on an agent running on a machine the customer
controls — and the clients (`omg`, WMD desktop/web) are **BSL source-available**, run
by the customer. Therefore:

- **Server-side, LUDO-keyed agents** do everything guardrailed / outward / mutating
  (customer comms, scheduling, migrations).
- **Client agents (BYO-key)** are **read / local / advisory only** — they reach the
  cluster's real capabilities only by sending an A2A request to a server-side agent.

### 3. One NATS, partitioned into trust-zone Accounts + tenant subject-perms
The substrate is shared; **the boundary is the NATS Account + the credential** — not a
second broker.

```
ONE NATS deployment
 ├─ Account EDGE     (client agents, BYO-key, untrusted)    edge.{account_id}.>
 ├─ Account CONTROL  (concierge, ops-copilot — PII-cleared)  ctl.{account_id}.>
 └─ Account INTERNAL (migration worker — NO PII)             int.migration.{account_id}.>
     ▲ cross-zone ONLY via explicit export/import (deny-by-default)
     ▲ per-credential pub/sub perms scoped to {account_id} (tenant isolation)
```

The PII rule stops being a convention and becomes **credential-enforced**: the INTERNAL
worker credential *cannot* subscribe to any `ctl.*` PII subject. This is a *stronger*
posture than today's stub-over-HTTP.

### 4. Tool-calling is vertical/in-process; A2A is horizontal/over-NATS
- **Tool-calling** — each agent calls *its own* `Tool`-protocol tools, in-process.
  Tools never leave the process. The migration worker's `load_to_odoo` is unreachable
  from any other agent.
- **A2A** — to get a migration done, an agent **sends a job** to
  `int.migration.{account_id}.*`; it does *not* call the worker's tools. Only A2A
  messages cross boundaries, and only what the Account exports. **This is the isolation
  guarantee.** Keep orchestrator→worker with structured briefs + summary returns; no
  peer "GroupChat".

## The registry is the subject space (no new service)

An agent "registers" by **subscribing to its capability subject**; discovery is a
request to that subject (queue groups load-balance instances). The **subject space is
the registry** — no registry service, no agent-card store. An "Agent Card" is the NATS
*micro* `INFO` reply. Activation falls out for free: **key present → the agent
subscribes → it's discoverable; no key → deterministic fallback.** Reuse and generalise
the worker's **JobType registry** (capability→handler).

## Guardrails: an ActionGate middleware in the existing chain

Don't build a guard service — reuse the middleware-chain pattern. `SafetyGate` already
*is* the migration guardrail (dry-run, verify-then-rollback). Add a sibling
**`ActionGate`** (rate-limit · quiet-hours · per-customer prefs · idempotency · audit ·
checkpoint-tier), shipped as a **shared lib** every server-side agent composes. It wraps
**act-tools** only, and is unreachable from EDGE (the Account wall), so a BYO-key client
cannot bypass it. The checkpoint tier reuses the `--ask-on-drift` backstop pattern.

## The agent map (operational excellence by audience)

| Agent | Audience | Placement | Tools |
|---|---|---|---|
| migration agent (today) | the system | INTERNAL, server | the ~37 migration primitives |
| **concierge** (lifecycle assistant) | customers | CONTROL, server | read: status/version/concerns · act (gated): email/SMS/schedule/nudge |
| **ops/admin copilot** | operators/admins | CONTROL, server | broad read · gated act |
| `omg` / WMD client agents | power users / customers | EDGE, BYO-key | read / local / advisory; A2A to server agents for anything real |
| `ludo-gateway` | — | — | **not an agent**; mints NATS creds from auth; routes |

## Net effect: the codebase shrinks

- **Collapse** the apps SSE-relay thread + the HTTP `ludo_agent_client` stub onto
  NATS-native request-reply + the existing JetStream projector.
- **Generalise, don't add:** JobType registry → capability registry; Contract B → a
  generic agent-event envelope; SafetyGate pattern → ActionGate.
- **No new:** registry service, agent-card store, guard service, second bus.

## Build order (substrate first; agents are kernel-phase)

1. **W1 Isolation substrate** — NATS trust-zone Accounts + export/import + per-tenant
   credentials; gateway mints creds; retire SSE relay + HTTP stub.
2. **W2 A2A-as-pattern** — Contract B → agent-event envelope; capability subjects;
   activatable-by-key subscription; reuse JobType registry.
3. **W3 ActionGate guardrails** — middleware in the chain; read/act tool split; audit
   via `outbound_mail`.
4. **W4 the agents (deferred)** — concierge + ops/admin copilot; client advisory agents.
   Only after W1–W3 + migration autonomy.
