# Isolation & the in-process runtime model

**Status:** living doc · **Scope:** Agentix kernel `[K]` (app-agnostic)

**Single source of truth for runtime isolation in `docs/`.** Sections 1–6 are the
canonical model with per-invariant landed status (code:
`src/agentix/drivers/cost.py` + `drivers/session.py`, `drivers/limiter.py`,
`storage/sqlite_store.py`, `storage/memory.py`, plus session.md §6); sections 7–8
are **DIRECTION**. The third
side of the Session triangle: [`session.md`](session.md) = the durable object,
[`context.md`](context.md) = the per-step window, **this doc = how concurrent runs
stay isolated at runtime**. The async execution model these invariants protect is
[`async.md`](async.md). Rewritten 2026-07-08 from the 2026-07-06 planning doc;
history in git.

---

## 1. The isolation axiom (canonical)

> **A Session is the unit of isolation.** One Session owns one context and one set of
> mutable state, scoped to a **task-tree rooted at a session task**. An **agent** is
> the actor that *runs* Sessions (1:N — many over its life). Isolation between
> Sessions is enforced **within a process** by per-task state-scoping
> (contextvar-inherited, structured concurrency) and **across processes** by
> NATS-Account walls (the A2A design). **Only distilled briefs/summaries cross any
> Session boundary** — child task, sub-agent, or A2A peer. Session-owned state is
> per-task; shared external capacity (LLM/target-system limits) is governed by one
> process-global limiter.

Two sub-principles everything references:

- **P-ISO-1 (identity).** Session = context = task-tree root. **Session ≠ agent**
  (agent:session is 1:N).
- **P-ISO-2 (crossing).** Every boundary crossing passes *distilled* context, never
  raw shared state.

## 2. Two isolation planes

| Plane | Boundary | Mechanism | Owner doc |
|---|---|---|---|
| **Intra-process** | Session ↔ Session in one worker | per-task state-scoping + structured concurrency | **this doc** |
| **Inter-process** | agent ↔ agent across workers | NATS trust-zone Accounts (deny-by-default export/import) | `ludo-agent/docs/proposals/agentic-cluster-a2a.md` Principle 4 |

The two planes share **exactly one law — P-ISO-2**. Stated canonically here;
referenced by context.md §8 and a2a Principle 4. **CRIE rule:** intra-process
isolation lives here; inter-process/inter-agent isolation lives in the a2a design —
reference it, don't restate it.

## 3. The concurrency invariants I1–I7

The rules that make `gather`-over-Sessions (or a second worker) safe. Each pairs a
per-task-scoping rule with the defect it neutralises. **I1–I6 = gather-safe within a
process; I7 = safe across processes.** Baseline: the production worker still runs
**single-flight by default** (`batch=1`, serial) — the invariants are what make
`batch>1` or a second replica safe, not a claim that concurrency is on.

- **I1 — Session context is task-scoped, never process-global.** *Fixes cost
  misattribution.* One task per Session (asyncio copies the contextvar snapshot into
  the task); binding is symmetric. **Landed:** `bind_session` returns a
  `contextvars.Token`, `unbind_session(token)` restores, and the `session_scope`
  async context manager wraps a run (`drivers/session.py`) — the never-unbound
  set is gone.
- **I2 — No shared mutable DB connection across Sessions; writes atomic + isolated.**
  **Half landed:** the cross-process half is in — WAL + `PRAGMA busy_timeout=30000`,
  so a second worker on the same file *waits* instead of failing `SQLITE_BUSY`
  (`storage/sqlite_store.py`, agentix#39). The in-process half is deferred: the
  store keeps one long-lived aiosqlite connection, safe only under single-flight —
  `gather` needs a per-task connection or a transaction lock (§8).
- **I3 — Session-shared filesystem state is scoped or locked.** **Kernel primitive
  landed:** `MemoryStore.lock(name)` namespaced advisory locks
  ([`memory.md`](memory.md) §3) cover same-process and cross-process contention;
  applying them to app-shared dirs (e.g. the reference app's rename maps) is the
  app's job.
- **I4 — Budget scoped per Session, ceilinged per account.** **Half landed:** each
  session owns its window budget (context.md) reporting into its own cost ledger
  (session.md §7). The **persisted per-account ceiling** that caps aggregate spend
  across parallel Sessions is control-plane-owned — direction (§7).
- **I5 — External-resource concurrency bounded globally, not per-instance.**
  **Landed:** `drivers/limiter.py` — one process-global semaphore (per event loop,
  default 8, `configure_driver_capacity` at startup) acquired around every model
  call (chat `complete`, stt `transcribe`); closes agentix#40. *The deliberate
  carve-out: session state is per-task, but shared external capacity is
  intentionally global.* Per-kind limits: [`drivers.md`](drivers.md) §8.
- **I6 — Structured concurrency: no session-child task outlives its Session.**
  Intra-session fan-out is awaited under the session root; no orphan `create_task`
  touching a finalized session — this is what "one task-tree" encodes, and it
  protects I1's contextvar copy. **Reference-app side:** the worker consumer's
  `batch>1` path fans the fetched batch out under a `TaskGroup` (per-task
  contextvar copy keeps I1 safe); `batch=1` stays the serial default.
- **I7 — (inter-process) Session single-flight lease + orphan reaper.** At most one
  worker runs a given `session_id`; a dead worker's session is reaped. **Landed:**
  schema v14 lease columns + `claim`/`renew`/`reap_expired_sessions`
  ([`session.md`](session.md) §6); the agent claims on start and renews each turn;
  the reaper is available but not auto-run while single-replica.

## 4. Intra-session concurrency (the sub-boundary)

A Session fans out child tasks (RPC, I/O). Child tasks inherit a **copy** of the
parent's contextvar context at `create_task` time → they read the correct
`session_id`, so cost books correctly (this is *why* I1 works). The only rule:
**structured concurrency** (I6) — children are awaited under the session root and
never touch session state after it finalizes. Shared *session-owned* resources
(working memory, app caches, the DB handle) still need per-child scoping or
serialization even inside one Session.

## 5. Session hierarchy: delegation & sub-agents

`delegate` / a sub-agent = a **child Session** with its **own context window**
(orchestrator context ≠ worker context) — **not** a sub-task sharing the parent's
session. Same identity model, two transports: **in-process** = a child
session-task; **over A2A** = a remote session in another NATS Account. Both obey
P-ISO-2 (a distilled brief in, a distilled summary out). The persisted link has
landed: `Session.parent_session_id` ([`session.md`](session.md) §1) — this doc owns
the runtime relationship; session.md owns the stored field. A2A crossing rules: a2a
design Principle 4 (referenced, not restated).

## 6. What is `[K]` vs `[A]`

- **`[K]` kernel:** the Session boundary, per-task state-scoping (`session_scope`),
  structured concurrency, the I1–I7 invariants, the global external-capacity
  limiter, the lease/reaper store API. Any app inherits gather-safe isolation.
- **`[A]` app:** the idempotency / resume-key provider (the reference app's
  record census is one implementation) + the source feeds. With
  `resume_or_create` generic (session.md §4), the abstraction is app-agnostic; the
  app supplies only what "work already done outside" means in its domain.

---

*Everything below is DIRECTION — converged design, not the code today.*

## 7. Enabling gather-over-Sessions

What remains before concurrent Sessions in one process (or `batch>1` by default):

- **I2's in-process half** — per-task DB connection or a transaction lock, so a
  commit flushes only that session's writes (agentix#39).
- **I4's account ceiling** — a persisted per-account spend ceiling enforced by the
  control plane, so N parallel sessions for one customer can't spend N×.
- Flip the consumer default past `batch=1` only after both close; I1/I3/I5/I6
  already hold.

## 8. Open decisions

- [ ] I2 mechanism: connection-per-task vs a transaction lock — which under
  aiosqlite.
- [ ] Where the per-account token-bucket limiter lives once there are multiple
  workers (I4/I5 across processes; the gateway as `account_id` authority is the
  natural owner).
- [ ] **SessionRuntime** as kernel component #21 (agentix#1): whether the runtime
  model (task-tree root, lease lifecycle, limiter wiring) gets a first-class object
  or stays a set of enforced invariants.
