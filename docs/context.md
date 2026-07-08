# Context Management

**Status:** living doc · **Scope:** Agentix kernel `[K]` (app-agnostic)

**Single source of truth for context management in `docs/`.** Sections 1–5 document
the landed kernel window subsystem (code: `src/agentix/core/context.py`,
`core/context_manager.py`, the dispatcher + TokenBudget integration); sections 6–9
are **DIRECTION**. This is the **policy layer** that decides *what occupies the model
window at every step* — it is NOT storage: [`memory.md`](memory.md) owns what memory
*is*; this doc owns what of it *enters the window*. Triangle companions:
[`session.md`](session.md) (the durable store of a run's context) and
[`isolation.md`](isolation.md) (runtime invariants I1–I7). Rewritten 2026-07-08 from
the 2026-07-06 planning worklog; history in git.

---

## 1. What context management is

Assemble → budget → compress → evict, once per model step, with **one owner**.
Before consolidation that logic was scattered — the dispatcher copied history and
injected working memory inline, `context.py` compressed, the TokenBudget middleware
checked the budget, and no one place decided what entered the window, in what
priority, and why. Closing that scatter is agentix#20; the `ContextManager` (§3) is
the owner.

## 2. Budget + compression primitives

`core/context.py` — the two building blocks the manager reuses rather than
reimplements (one budget type, one compression path):

- `ContextBudget` — the per-call token budget: `max_input_tokens` (default 16k)
  and `keep_recent` (turns kept verbatim under compression).
- `summarise_oldest_tool_results(messages, max_input_tokens)` — the default
  `CompressionStrategy`. Under budget → identity. Over budget: **system messages
  are always kept verbatim** (this is why working memory survives, memory.md §2),
  the most recent non-system messages are kept, and everything between collapses
  into a single summary message enumerating the elided tool calls — bounding
  tokens without losing the shape of the recent exchange. Deterministic: same
  input, same output. Strategies are pluggable.

## 3. `ContextManager` — the window owner

`core/context_manager.py`. Stateless across turns; one object that assembles,
compresses, and reports.

`assemble(base_messages, working_memory_render=…, compress=…)`:

- Working memory becomes a `system` message inserted **after the leading system
  prompt** — the primary prompt stays at index 0, and being `system` is what makes
  the log survive compression.
- With `compress=True` the window is compressed to budget; `compress=False` does
  assembly + report only, leaving compression to whoever owns the budget step (§5).
- Every surviving message is classified into a priority tier:

| Tier | Value | Survives | What it holds |
|---|---|---|---|
| `SYSTEM` | 0 | never evicted | system prompt / guardrails |
| `WORKING_MEMORY` | 1 | survives compression | tried / failed / learned |
| `SUMMARY` | 2 | stands in for elided history | the compression summary |
| `HISTORY` | 3 | first to be compressed away | conversation turns |

Lower number survives longer under pressure; richer tiers (retrieved memory) slot
in between as they are wired (§6).

`compress_if_needed(messages)` returns `(messages, did_compress)` where
`did_compress` is a **token-delta** signal, not a message-count proxy — a
body-shrinking strategy changes tokens without changing counts, and a budget guard
must not abort prematurely. This is the one compression path (it superseded the
old `ContextBuilder`).

Tests: `tests/unit/core/test_context_manager.py`.

## 4. The window report

`AssembledContext.window_report()` — the per-turn observability surface: a
JSON-serialisable snapshot of exactly what the model saw and why.

```
{ total_tokens, budget_tokens, compressed, over_budget,
  messages: [ { tier, role, tokens, reason }, … ] }
```

Vocabulary: this is the **window report** (renamed from the context "X-ray" —
*X-Ray* stays reserved for the read-only estimate scan).

## 5. Integration — one assembly path, one budget step

- The **dispatcher** builds every LLM request through
  `ContextManager.assemble(..., compress=False)` (`agent_dispatcher.py`) — the
  inline working-memory injection is gone; assembly happens in exactly one place.
- The **TokenBudget middleware** owns the budget step: before dispatch, if the
  window is over budget it calls `compress_if_needed` — compress-before-abort. If
  compression cannot shrink further, the turn aborts cleanly instead of invoking
  the provider. The lever is always wired (the middleware default-constructs a
  manager).
- The split (assemble in the dispatcher, budget in the middleware) is deliberate
  for now; unifying them into a single budget step is the next slice (§9).

---

*Everything below is DIRECTION — converged design, not the code today.*

## 6. The full tier ladder + retrieval gating

- Target eviction order: **guardrails/safety (never evict) > task/goal > active
  working set > retrieved memory > history**. Today's four tiers are the concrete
  subset; retrieved memory slots between SUMMARY and HISTORY when wired.
- **Retrieval gating** — decide *when* and *how much* to pull from memory, ranked
  by relevance. Over-retrieval poisons the window; don't dump. Instrument before
  optimising — the window report (§4) exists so policy changes are measured, not
  guessed.
- **Generalise progressive disclosure** — skills' summary-in / body-on-demand
  pattern ([`skills.md`](skills.md)) applied to tools and memory: cheap
  name+description in the window, full body on demand.

## 7. Security + caching

- **Untrusted context is a security boundary.** Retrieved memory and tool outputs
  are injection vectors; safety instructions must be un-evictable (Tier SYSTEM)
  and structurally separated from untrusted content.
- **Cache-prefix contract** — deterministic assembly is also a cost lever: a
  byte-stable window prefix maximises prompt-cache hits. What exactly must stay
  byte-stable is an open decision (§9).

## 8. Alignment with session-management

Canonical contract + genericity check: [`session.md`](session.md) § Session ↔
Context alignment (single source of truth — not restated here). In short: **the
Session is the durable store of a run's context; the ContextManager is the
per-step policy over it — one object, two sides.** Remaining misalignment: the
session snapshot still persists raw `messages` (session.md clause 3); resume is
wired and kernel-generic (`resume_or_create`). Policy-side consequences:

- The ContextManager writes the **managed** window that the Session snapshots (not
  raw history) — compression and the session's snapshot policy are the same
  co-designed work.
- The ContextManager owns the per-step **window/token** budget and reports
  consumption into the Session's **cost** ledger — two budgets, one flow.
- The per-step budget is *scoped per session-task* and *ceilinged per customer* by
  [`isolation.md`](isolation.md) I4/I5, so parallel sessions don't spend N×.
- Multi-agent: per-agent windows — a sub-agent returns a **distilled conclusion**,
  never raw context. The crossing law is canonical as [`isolation.md`](isolation.md)
  P-ISO-2; inter-agent NATS-Account isolation is
  `ludo-agent/docs/proposals/agentic-cluster-a2a.md`.
- Every context policy should ship behind eval (Verdict graders,
  `ludo-agent/docs/proposals/eval-validation.md`) as a measurable experiment.

## 9. Open decisions

- [ ] Budget-step unification: fold the dispatcher's `compress=False` assembly and
  the TokenBudget compression into one owned step.
- [ ] Retrieval-gating design (relevance ranking, budget share per tier).
- [ ] Cache-prefix contract — what must stay byte-stable for prompt-cache hits.
- [ ] Summary cadence + what is lossy-safe to compress vs must-be-verbatim.
- [ ] Shared managed-context-state object shape (what the Session snapshots) —
  co-owned with session.md (clause 3).
- [ ] `[K]`/`[A]` split of context *sources* (the app feeds sources; the policy is
  kernel).
