# Session Management

**Status:** planning · **Scope:** Agentix kernel `[K]` (Session abstraction) + LUDO app `[A]` (run orchestration) · **Opened:** 2026-07-06

Living design + worklog for the **Session** — the agent's single run (1:1 with a
control-plane Migration), the ephemeral `s_…` id. Records what exists today (grounded in
code) and the gaps the *rest* of the Agentix architecture will force. Companion to
[`context.md`](context.md) (a session snapshot carries a context window — they intersect).

---

## What a Session is

`Migration` (control-plane) -> **`Session`** (agent's run, 1:1; `s_…`; stored as
`ludo_session_id` control-plane-side, `sessions.id` agent-side) -> `N Jobs` -> `Turns`
(Cortex round-trips). Vocabulary lock: workspace `CLAUDE.md` § Execution model.

## What EXISTS today (considerations already taken)

Grounded map (file:line as of 2026-07-06):

- **Session is a first-class KERNEL abstraction** — `agentix/core/session.py` owns the
  object + `create_session` / `save` / `resume_from`; the `s_…` id is minted here. App scope
  is pushed into an opaque `app_meta` blob, so the kernel stays Odoo-free. Clean `[K]/[A]`
  split. `agentix/storage/sqlite_store.py` owns the `sessions` + `turns` schema
  (`_SCHEMA_VERSION = 12`). The app only subclasses (`ludo/storage/ludo_sqlite.py`) to add
  migration tables + reads scope from `app_meta`.
- **PII-safe identity** — `sessions.customer_id` = the opaque `account_id`; `slug->account_id`
  resolution happens only at the operator/CLI edge (`ludo/cli/_customer_provider.py`), never
  in the worker (`worker/registry.py` passes `msg.account_id` straight through).
- **Two-store persistence, crash-correct ordering** — SQLite = metadata + `checkpoint`
  pointer; MinIO = full snapshot blob (`blobs/{cust}/checkpoints/{sid}/{name}.json`).
  `save()` writes MinIO-then-SQLite deliberately (orphan blob is harmless; dangling pointer
  is not). `session.py:98-111`.
- **State-checkpoint WRITE path is live** — a `"latest"` snapshot is cut after every turn
  (dispatcher-throttled, `agent_dispatcher.py` cadence). Captures `messages`, `working_memory`
  (tried/failed/learned), budget/tokens/cost, `status`, `app_meta`.
- **Turn tracking in the kernel** — `turns` table + `turns_fts` (FTS5) mirror, written as a
  side-effect of the `TrajectoryCapture` middleware, not the action layer.
- **Cost + honesty accounting** — per-session/turn token + `cost_usd` deltas; `outcome` +
  `intervention_type` columns feed the autonomy metric directly.
- **Resumability as row-level idempotency** — deterministic-xmlid census
  (`actions/.../drain_model.py`) makes broker redelivery a no-op-or-update (Principle 3);
  intra-tool cursor resume via `resume_from_source_id_gt`. At-least-once + idempotent
  execution, no dedup table.
- **Per-customer memory lock** — serialises memory writes across parallel sessions for the
  same customer (`middleware/memory_maintain.py` -> `storage/memory.py:lock_for_customer`).
- `status` lifecycle: `running | paused | completed | failed`. Read API: `GET /sessions[/{id}]`.

## The GAPS — mapped to the rest of the architecture

Theme: session *write* + *row-level re-run* are live, but session *identity, ownership, and
in-context recovery* are unwired — and the remaining kernel components lean on exactly those.
Ranked by leverage.

1. **In-context resume is built but wired to nothing — and the live substitute is
   app-specific.** `resume_from` fully rebuilds messages/working_memory but is called only in
   tests; production always starts a *fresh* `Session`. Every redelivery re-pays Cortex tokens
   and discards within-session tried/failed/learned progress. Row census protects *data*, not
   *reasoning state* — **and the census is Odoo-specific (`ir.model.data` xmlids), so a
   non-migration app on Agentix inherits *no* recovery at all.** → Wire
   `worker/consumer -> resume_from` *and* make resume kernel-generic (see genericity clause in
   the alignment contract). Highest-leverage fix; the generic infra already exists.
2. **No session ownership/lease or orphan reaper (blocks leaving single-replica).** No
   session-level lock / single-flight. Safe today only via single-replica + idempotent census.
   When the **gateway + broker** fan jobs to N workers, two workers can run the same
   `session_id`; a dead worker leaves a session `running` forever (no heartbeat/TTL).
   → Session lease/claim (gateway is the `account_id` authority = natural owner) + liveness reaper.
3. **Operator-review "checkpoint" is a placeholder — the human-oversight seam.**
   `checkpoint_requested` event + `checkpoint_required` flag are *reserved, no emitter*; named
   phase checkpoints (`blueprint_generated`…) declared but unconsumed; `status="paused"` has no
   resume-from-paused caller. The **autonomy bar**, `estimate`/`dry-run` modes, and
   **activatable agents** all depend on pause->operator-decision->resume, which is a no-op today.
4. **Session ↔ Job state not reconciled with the broker.** Snapshot captures turns, not the
   Job queue — no pending/done-Job set, so the session can't answer "which Jobs remain."
   arch.md flags the "future first-class per-Job row." Crash granularity = turn snapshot + row
   census, with queue position lost.
5. **Control-plane ↔ agent session-id binding is documented, not stored.** Gateway assigns
   `ludo_session_id`; agent uses `session.id`; the link lives only in `worker/payload.py`
   prose. The gateway needs it to project resumable SSE + drive resume.
   → Persist e.g. `sessions.control_plane_id`.
6. **Snapshot = unbounded raw history → the core misalignment with context-management.**
   The blob stores full `messages`; long sessions grow without bound and resume would
   rehydrate an ever-larger window. Resolved by the alignment contract below — the snapshot
   must carry the *managed* window, not raw history. See [`context.md`](context.md).
7. **Session is the natural eval unit, only half-connected.** `outcome`/`intervention_type`
   feed the autonomy metric, and turns+FTS+working_memory are a ready trajectory substrate,
   but there's no systematic hand-off of a completed session into **Verdict / Grader B**.
   Cheap win — data already exists.
8. **A2A introduces a session hierarchy not yet modelled.** When `delegate` spawns sub-agent
   work, there's no parent/child session linkage or isolation contract (sub-agent returns a
   distilled conclusion, not raw context). Needs a session-relationship model before A2A lands.

## Session ↔ Context alignment (canonical contract)

Session-management and context-management are **the same object seen from two sides**: the
Session is the *durable store* of a run's context; the ContextManager ([`context.md`](context.md))
is the *per-step policy* over it. They are **NOT aligned today** — the snapshot persists raw
`messages`, `working_memory` is an ad-hoc second compressor, and the cost budget and the
window budget are unrelated. This contract aligns them (single source of truth; `context.md`
links here).

1. **One managed context state, kernel-owned.** The Session persists a single working context
   (summary + recent messages + `working_memory`, *post-eviction*); the ContextManager is its
   only shaper. Both are `[K]` — the app never touches the window shape, only feeds *sources*
   (via `app_meta` + provider extension points).
2. **Session = durable ledger; ContextManager = per-step policy.** Session owns persistence
   (snapshot/resume) + cost accounting; ContextManager owns assemble/budget/compress/evict. No
   compression logic in the action or session layer.
3. **Snapshot stores the managed window, not raw history** — so the blob and resume stay
   bounded regardless of session length.
4. **Resume rehydrates *through* the ContextManager — and resume must be kernel-generic.**
   `resume_from` reconstructs the managed context; the next step assembles from it. Today the
   *live* recovery path is the Odoo-xmlid census (app-specific), so the generic kernel delivers
   no recovery to a non-migration app. Fix: wire `resume_from` **and** define a generic
   **idempotency / resume-key extension point** the app implements (LUDO's xmlid census = one
   impl). This makes session.md **S0 (wire resume)** and context.md **S2 (compression + resume)**
   the *same co-designed work* — not two passes.
5. **Two budgets, reconciled.** ContextManager owns the per-step *window/token* budget and
   reports consumption into the Session's *cost* ledger (`total_*_tokens`, `cost_usd`). One
   flow, no double-count.
6. **`working_memory` is the seed, not a rival.** Today's session-owned tried/failed/learned
   distillation folds into the ContextManager's managed state — one compression owner, not two
   (CRIE).

**Genericity check:** with this contract the *abstraction* is app-agnostic (Session +
ContextManager `[K]`; migration specifics stay in `app_meta` + providers). The one thing that
is *not* generic today is the live resume mechanism (clause 4) — closing that is what makes
sessions+context genuinely reusable across apps.

## Open decisions

- [ ] Where the session lease lives (gateway-owned vs agent-owned vs broker consumer group).
- [ ] Persist `control_plane_id` on `sessions`, or keep the mapping gateway-side only?
- [ ] Does `resume_from` rehydrate on every redelivery, or only when a snapshot is "fresh enough"?
- [ ] Per-Job persistence: first-class `jobs` row vs. deriving from broker ack state.
- [ ] Snapshot content policy once context-management lands (raw vs. managed window).
- [ ] Session-hierarchy shape for A2A (parent_session_id? separate correlation id?).
- [ ] The generic idempotency / resume-key extension point (LUDO xmlid census = one impl) — its interface.
- [ ] Budget split: ContextManager owns the window/token budget; how it reconciles into the `sessions` cost ledger.

## Roadmap / slices

Sequenced by leverage + dependency:

- **S0 — Wire in-context resume** (`consumer -> resume_from`). Infra exists; biggest single win.
- **S1 — Operator-checkpoint seam** (emit `checkpoint_requested`, wire pause->resume). Unlocks
  the autonomy bar + activation.
- **S2 — Session lease + orphan reaper.** Becomes urgent the day single-replica is dropped.
- **S3 — Control-plane id binding + per-Job state + eval hand-off.** As gateway/eval land.
- **S4 — A2A session hierarchy.** As A2A lands.

## Worklog

- **2026-07-06** — doc opened from a two-part code map (session lifecycle/state/turns +
  checkpoint/resume). What exists + 8 gaps captured. No code yet.
- **2026-07-06** — added the canonical Session↔Context alignment contract (6 clauses +
  genericity check); flagged that the only live recovery path (Odoo-xmlid census) is
  app-specific, so a generic kernel needs a resume-key extension point. Cross-linked `context.md`.
