# Context Management

**Status:** planning · **Scope:** Agentix kernel `[K]` (app-agnostic) · **Opened:** 2026-07-06

Living design + worklog for how the kernel decides *what occupies the model window at
every step*. Update as decisions land. Not a numbered spec — when a slice is ready to
build, cut a `specs/` entry and link it back here.

---

## What this is (and isn't)

Context-management is the **policy layer**: assemble -> budget -> compress -> evict, once
per model step. It is NOT storage. Storage = memory tiers / knowledge substrate. This layer
*decides what enters the window* from those stores + tools + skills + history.

Today that logic is scattered (memory retrieval, skill disclosure, history handling, tool
schemas each assemble themselves). Consolidating it into one owner is the CRIE win.

## Assets to build on (already in the cluster)

- **Progressive disclosure** — Skills `S3->S1->S0` cascade + `SkillCatalog`. This IS
  context-management; generalise the same summary-in / body-on-demand pattern to tools,
  memory, knowledge. (see `docs/proposals/tool-skill-calling.md`, `agent-skills-catalog.md`)
- **Checkpoints** — `core/checkpoints.py`; context reconstruction on resume rides this spine.
- **Eval** — Verdict + Grader A (responses) / B (outcomes). Every context policy must be
  measurable here. (see `docs/proposals/eval-validation.md`)
- **Memory tiers** — `consult_memory`, applied_memory_rules (retrieval source, not the policy).
- **X-rays / metrics** — introspection surface for "what was in-window and why".

## Design dimensions (the checklist)

1. **Budget & accounting** — one explicit token budget per step, one owner. Shared pool:
   guardrails, goal, working set, retrieved memory, tool outputs, history all compete.
   *Instrument before optimising* — measure what's actually in-window first.
2. **Deterministic assembly + priority tiers** — fixed pipeline, fixed evict-order. Also a
   cost lever: a stable prefix maximises prompt-cache hits.
3. **Retrieval gating** — decide *when* / *how much* to pull from memory, ranked by
   relevance. Over-retrieval poisons the window. Don't dump.
4. **Compression & eviction** — rolling summary, tool-output truncation/dedup,
   checkpoint-anchored reconstruction. Define lossy-safe vs. must-be-verbatim.
5. **Untrusted context = security** — retrieved memory + tool outputs are injection vectors.
   Safety instructions un-evictable and structurally separated from untrusted content.
6. **Multi-agent isolation (A2A)** — per-agent windows; sub-agents return distilled
   conclusions, not raw context. Orchestrator context != worker context.
7. **Observability** — per-step X-ray: what entered, why, token cost. Ties to metrics + omg.

## Architecture direction (draft)

- A first-class kernel component — `ContextManager` / context-assembler, tagged `[K]`.
- Single seam between the stores (memory/tools/skills/knowledge) and the executor: hands
  back a **budgeted, ordered, safety-partitioned** window.
- App (LUDO) supplies only the *sources*; the assembly/budget/evict policy is kernel.
- CRIE: this component replaces the scattered per-source assembly.

**Priority tiers (eviction order), draft — highest survives:**
`guardrails/safety (never evict) > task/goal > active working set > retrieved memory > history`

## Open decisions

- [ ] Component boundary: standalone `ContextManager` vs. folded into Cortex spine?
- [ ] Who owns the token budget, and how it's threaded to sub-agents.
- [ ] Cache-prefix contract — what must stay byte-stable for prompt-cache hits.
- [ ] Summary cadence + what is lossy-safe to compress.
- [ ] How a context policy plugs into eval (A/B) as a measurable experiment.
- [ ] `[K]`/`[A]` split of context *sources*.
- [ ] New kernel component # in the inventory (kernel-init #1) — likely #20.

## Roadmap / slices

Sequence is instrument-first; each slice ships behind eval.

- **S0 — Instrument + budget core.** ContextManager assembles deterministically, enforces one
  budget, X-rays the window per step. Foundation.
- **S1 — Generalise progressive disclosure.** Extend `S3->S1->S0` to tools/memory/knowledge.
  Highest leverage, lowest risk, reuses a proven mechanism.
- **S2 — Compression + checkpoint resume.** Long-running sessions.
- **S3 — Eval harness for context policies.** Make every change measurable.

## Worklog

- **2026-07-06** — doc opened. Framing, dimensions, assets, architecture direction captured.
  First slice not yet chosen (S0 recommended). No code yet.
