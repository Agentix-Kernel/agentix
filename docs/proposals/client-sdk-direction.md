# Client SDK direction — build-vs-skip the behavioural client layer

> **STATUS: DECISION — design-first note, per euroblaze/agentix#57.** Decides whether to
> build a thin per-language client layer (HTTP + auth + retry) around the generated types.
> Related: #8 (type codegen), #9 (client know-how), [`../contracts-consumer-guide.md`](../contracts-consumer-guide.md),
> euroblaze/ludo-cli#7, euroblaze/ludo-desktop#4/#5.

## Problem

Every thin client re-implements the same behavioural stack around Contract A:
HTTP wrapper + bearer/PKCE auth + SSE reconnect with backoff + JSON decode. Today:

- **Python** — `ludo-cli` `src/omg/client.py` (exponential + jitter, 0.5s→30s, bounded, transient-status filter). The most complete.
- **Swift** — `ludo-desktop` `LiveAPIClient.swift` (aligned to the policy in CRIE-003 #9; before that it had drifted: no jitter, 1s→8s, unprefixed paths).
- **TS** — `ludo-webapps` per-app `useApi`/fetch wrappers.

Types are being solved by codegen (#8). The *behaviour* is not — and the desktop drift (#8/#9) is exactly what an unwritten, uncodified policy produces.

## Decision: SKIP a generated multi-language SDK. Codify the policy; keep thin hand-clients.

Rationale (aligned with "simple-first, minimise tech-debt to zero"):

- Only **three** clients exist, each already has a working thin client. A generated behavioural SDK (a per-language HTTP/auth/retry framework + its generator) is high-effort, high-maintenance, and low marginal value — a framework for three hand-written files.
- The actual defect was **drift from an unwritten policy**, not missing abstraction. The fix is to *write the policy once* and conform each client to it — not to build a code generator.
- Auth (PKCE), SSE framing, and reconcile-on-reconnect are already documented once in [`contracts-consumer-guide.md`](../contracts-consumer-guide.md); retry/backoff was the gap.

### What we do instead (lightweight, per-language)

| Language | Types | Behaviour | Action |
|---|---|---|---|
| Python | generated (#8) | `omg/client.py` is the reference impl | keep; treat as the policy exemplar |
| Swift | generated (#8) | `LiveAPIClient.swift` | keep; aligned in #9; backoff unit test added |
| TS | generated (#8) | per-app `useApi` | keep; align to the policy when next touched |

1. **One canonical policy spec** — extend [`contracts-consumer-guide.md`](../contracts-consumer-guide.md) with a "Retry & backoff" section (the numbers below) so every client conforms to the *same* documented contract. That spec is the single source of truth, not a shared binary.
2. **One conformance check per client** — a unit test asserting the backoff sequence + transient-status filter against the spec (desktop got one in #9; cli already has coverage; TS adds one when it grows a real client).
3. **Revisit if a 4th language or a mobile app lands** — at that point the duplication crosses the threshold where a generated behavioural layer pays for itself. Not before.

### Canonical retry/backoff policy (to fold into the consumer guide)

- Exponential backoff, base **0.5s**, cap **30s**, **full jitter** (`random(base/2 … min(base·2^n, cap))`).
- Retry only **transient** failures: network errors, HTTP **429** and **5xx**. Non-transient 4xx (401/403/404) stop, they won't self-heal.
- SSE streams reconnect **forever by design** (live feed), jittered; command/query calls use a **bounded** attempt count.
- On SSE reconnect: `GET /migrations/{id}` to reconcile, then resume from `Last-Event-ID`.

## Consequence

No new package, no generator, no conformance harness to maintain. One policy doc + three small per-client tests. If the client count grows, this note is the trigger to reopen the build decision.
