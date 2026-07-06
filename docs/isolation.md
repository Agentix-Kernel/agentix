# Isolation & the in-process runtime model

**Status:** planning · **Scope:** Agentix kernel `[K]` · **Opened:** 2026-07-06

The third side of the Session triangle: [`session.md`](session.md) = the durable object,
[`context.md`](context.md) = the per-step window, **this doc = how concurrent runs stay
isolated at runtime**. Reconciles session + context + multi-agent + genericity with
asyncio/concurrency into one model. Aligns to `CLAUDE.md` § Execution model
(Migration→Session→Job→Turn).

---

## The isolation axiom (canonical)

> **A Session is the unit of isolation.** One Session owns one context and one set of mutable
> state, scoped to a **task-tree rooted at a session task**. An **agent** is the actor that
> *runs* Sessions (1:N — many over its life, serially today, concurrently once `gather`-ed).
> Isolation between Sessions is enforced **within a process** by per-task state-scoping
> (contextvar-inherited, structured concurrency) and **across processes** by NATS-Account walls
> (the A2A proposal). **Only distilled briefs/summaries cross any Session boundary** — child
> task, sub-agent, or A2A peer. Session-owned state is per-task; shared external capacity
> (LLM/Odoo limits) is governed by one process-global limiter.

Two sub-principles everything references:
- **P-ISO-1 (identity).** Session = context = task-tree root. **Session ≠ agent** (agent:session is 1:N).
- **P-ISO-2 (crossing).** Every boundary crossing passes *distilled* context, never raw shared state.

## Two isolation planes

| Plane | Boundary | Mechanism | Owner doc |
|---|---|---|---|
| **Intra-process** | Session ↔ Session in one worker | per-task state-scoping + structured concurrency | **this doc** |
| **Inter-process** | agent ↔ agent across workers | NATS trust-zone Accounts (deny-by-default export/import) | [`proposals/agentic-cluster-a2a.md`](proposals/agentic-cluster-a2a.md) Principle 4 |

The two planes share **exactly one law — P-ISO-2** (only distilled context crosses). Stated
canonically here; referenced by context.md dim 6 and a2a Principle 4. **CRIE rule:**
intra-process isolation lives here; inter-process/inter-agent isolation lives in the a2a
proposal — reference it, don't restate it.

## What EXISTS today (grounded)

- **Single-flight is the only isolation.** The worker runs **one job at a time**
  (`worker/consumer.py`: `batch=1`, serial `for m in msgs: await run_job`, no
  `gather`/`create_task`). Two Sessions never interleave in one process → today's safety is
  single-flight, not per-task scoping.
- **Intra-session async IS real** — a Session already fans Odoo RPC out under a per-instance
  `asyncio.Semaphore` (`odoo/client.py`), with threaded SQLite (aiosqlite) + MinIO (`to_thread`).
  So a Session is *already* a task-tree; concurrency exists **inside** a run, not across runs.
- **Per-session isolation that's sound:** Engine/dispatcher/registry/ToolContext built fresh per
  run; MinIO keys session-scoped; event bus keyed by `session_id`; atomic SQL `+=` cost increment.
- **The interleave-unsafe shared state** (masked only by single-flight): a never-unbound
  `bind_session` ContextVar; one shared `aiosqlite` connection; unlocked shared rename-map dirs;
  no persisted per-customer budget ceiling; per-instance (not global) LLM/Odoo limits.

## The concurrency invariants (canonical — the actionable core)

The rules that make `gather`-over-Sessions (or a 2nd worker) safe. Each = a per-task-scoping rule
+ the defect it neutralises. **I1–I6 = gather-safe within a process; I7 = safe across processes.**

- **I1 — Session context is task-scoped, never process-global.** One `create_task` per Session
  (asyncio copies the contextvar snapshot into the task); `bind_session` entered/exited
  *symmetrically* in that scope (context-manager, not a never-unbound set). *Fixes cost
  misattribution.* The create_task context-copy already does most of the work — a session-per-task
  model fixes it almost for free.
- **I2 — No shared mutable DB connection across Sessions; writes atomic + isolated.** Connection
  per session-task (or a real transaction lock); `execute`+`commit` wrapped so a commit flushes
  only that session's writes; `busy_timeout` + WAL so a 2nd process *waits* instead of `SQLITE_BUSY`.
- **I3 — Session-shared filesystem state is scoped or locked.** Rename-map / snapshot-restore dirs
  keyed per session (or version-pair) and guarded by the existing `lock_for_customer` before
  snapshot/restore.
- **I4 — Budget scoped per Session, ceilinged per customer.** Each session-task owns its
  window/token budget (context.md) reporting into its own cost ledger (session.md clause 5); a
  **persisted per-account ceiling** caps aggregate spend across parallel Sessions.
- **I5 — External-resource concurrency bounded globally, not per-instance.** LLM + Odoo go through
  a **shared per-account/per-deployment limiter**, not a per-Session semaphore. *The deliberate
  carve-out: session state is per-task, but shared external capacity is intentionally global.*
- **I6 — Structured concurrency: no session-child task outlives its Session.** Intra-session
  fan-out awaited under the session root (TaskGroup-style); no orphan `create_task` touching a
  finalized session. This is what "one task-tree" encodes; it protects I1's contextvar copy.
- **I7 — (inter-process) Session single-flight lease + orphan reaper.** At most one worker runs a
  given `session_id`; a dead worker's session is reaped. Gateway = `account_id` authority = owner.
  *Not part of the intra-process gather-safe set — the cross-process extension.*

**Defect → invariant map:** never-unbound ContextVar → **I1** · shared aiosqlite conn / no
busy_timeout → **I2** · unlocked rename dirs → **I3** · no per-customer ceiling → **I4** ·
per-instance LLM/Odoo limit → **I5** · structured-concurrency / contextvar-copy → **I6** · no
lease/reaper → **I7**. (Defects catalogued in session.md GAP #2 + the multi-agent readiness analysis.)

## Intra-session concurrency (the sub-boundary)

A Session fans out child tasks (Odoo RPC, I/O). Child tasks inherit a **copy** of the parent's
contextvar context at `create_task` time → they read the correct `session_id`, so cost books
correctly (this is *why* I1 works). The only rule: **structured concurrency** (I6) — children are
awaited under the session root and never touch session state after it finalizes. Shared
*session-owned* resources (working_memory, the rename-map, the DB handle) still need per-child
scoping or serialization even inside one Session.

## Session hierarchy: delegation & sub-agents

`delegate` / a sub-agent = a **child Session** with its **own context window** (context.md dim 6:
orchestrator context ≠ worker context) — **not** a sub-task sharing the parent's session. Same
identity model, two transports: **in-process** = a child session-task; **over A2A** = a remote
session in another NATS Account. Both obey P-ISO-2 (a distilled brief in, a distilled summary out).
This needs the `parent_session_id`/correlation field the flat `Session` forbids today
(`extra="forbid"`) — so **isolation.md owns the runtime relationship; session.md owns the persisted
field** (its GAP #8 + open decision). A2A crossing rules: a2a proposal Principle 4 (referenced).

## What is `[K]` vs `[A]`

- **`[K]` kernel:** the Session boundary, per-task state-scoping, structured concurrency, the I1–I7
  invariants, the global external-capacity limiter. Generic — any app inherits gather-safe isolation.
- **`[A]` app:** the resume-key / idempotency provider (LUDO's Odoo-xmlid census = one impl) + the
  source feeds. Genericity closes only when the kernel owns I1–I7 rather than leaning on an app
  trick (session.md clause 4).

## Open decisions

- [ ] `asyncio.TaskGroup` vs. manual `gather` for the session task-tree (structured-concurrency primitive).
- [ ] Connection-per-task vs. a transaction lock for I2 — which under aiosqlite.
- [ ] Where the global external-capacity limiter lives (per-account token-bucket owner).
- [ ] Is I7 (lease/reaper) folded into the runtime component or split as an inter-process concern?
- [ ] Kernel component # (agentix#1): ContextManager = #20 (context.md); this **SessionRuntime** = #21.

## Roadmap / slices

Isolation only *bites* once concurrency is introduced, so this tracks the concurrency-enablement path:

- **S0 — Symmetric session binding + per-task scoping** (I1). Cheap; also fixes the live cost leak.
- **S1 — DB + filesystem interleave-safety** (I2, I3). Prereq for any in-process `gather`.
- **S2 — Global external-capacity limiter + per-customer ceiling** (I4, I5).
- **S3 — Structured-concurrency the session task-tree** (I6); then enable `gather`-over-Sessions.
- **S4 — Session lease + reaper** (I7) — cross-process; with the gateway.
- **S5 — Session hierarchy field** (parent/correlation) — unblocks in-proc + A2A delegation.

## Worklog

- **2026-07-06** — doc opened to reconcile session + context + multi-agent + genericity with
  asyncio/concurrency. Canonical: the isolation axiom (P-ISO-1 / P-ISO-2), the two planes, and the
  I1–I7 invariants (each mapped to a concrete defect). References session.md (durable object +
  alignment contract), context.md (window policy), a2a proposal (inter-process plane).
