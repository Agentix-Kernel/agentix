# Runtime eval & validation mini-framework (`ludo.eval`)

> **STATUS: DIRECTION — converged design, not the code today.** A lean, agent-agnostic
> **runtime** layer for (A) validating LLM responses and (B) validating agentic task
> outcomes. **Runtime-only this round** — no offline eval harness / golden datasets / CI
> regression scoring. Reuses what already exists; adds one new primitive (an activatable
> judge). Substrate for the Cortex verify step ([#471](https://github.com/euroblaze/ludo/issues/471)),
> ActionGate ([#495](https://github.com/euroblaze/ludo/issues/495)), and the W4 agents
> ([#496](https://github.com/euroblaze/ludo/issues/496)).

## The insight

Eval + validation already exist in LUDO — but **migration-specific and scattered**. The
mini-framework **generalises them into one agent-agnostic library** and adds the single
missing primitive (LLM-as-judge). Net: less duplication, every agent (migration /
concierge / ops) gets the same validation spine.

## One spine, two graders

```
                         ┌───────────────── Verdict ─────────────────┐
                         │  passed · findings[hard|advisory] ·        │
                         │  confidence · evidence · provenance        │
                         └────────────────────────────────────────────┘
        Grader A — LLM RESPONSES                Grader B — AGENTIC OUTCOMES
        (the cognitive output)                  (did the task accomplish its goal)
        ├ SchemaCheck      (reuse)              ├ OutcomeContract (generalise verify_migration)
        ├ GroundednessCheck(reuse)              ├ honest outcome  (reuse compute_outcome)
        ├ AdversarialCheck (reuse)              ├ claim_mismatch  (reuse — no lying)
        └ JudgeCheck(rubric) ← NEW, activatable └ → intervention_type / surprises (reuse)
```

### Spine — `Verdict`
Consolidate the scattered result types into one agent-agnostic shape: `passed: bool` ·
`findings: [Finding(severity: hard|advisory, code, detail, evidence)]` · `confidence`
(multi-dimensional) · `provenance` (model, cost, elapsed, checks_run). **Reuse**
`core/diagnosis.py` (`Finding`/`Confidence`/`Evidence`/`Provenance`) and
`verify_migration.py`'s hard-vs-advisory tiering — lift them into `ludo.eval` so diagnosis
and verify both adopt it (code shrinks).

### Grader A — validate an LLM response (composable checks → Verdict)
- **SchemaCheck** — pydantic structured-output validation (reuse the per-tool
  `input/output_schema` + `model_validator` coercion pattern).
- **GroundednessCheck** — the claim must cite evidence actually present (reuse diagnose's
  `_adversarial_type_check` "cites evidence in the real failures" logic, generalised).
- **AdversarialCheck** — reuse `llm/adversarial.py::refute(provider, claim, prompt)` as-is.
- **JudgeCheck(rubric)** — **NEW, the only new primitive**: `judge(response, rubric) →
  Verdict` over the LLM router. **Activatable** (fires only when an LLM key is present);
  **best-effort** (failure → advisory, never a silent hard-block) exactly like
  `adversarial.py`. Scores open-ended/free-form responses against declared criteria.

### Grader B — validate an agentic outcome (declarative, honest)
- **OutcomeContract** — lift `verify_migration`'s checks + `VerifyContract` (count · sum ·
  required · state-distribution · required-children; hard vs advisory) into an
  **agent-agnostic contract**. `verify_migration` becomes *one instance*; each agent
  declares its own:
  - *migration*: the existing shape contract.
  - *concierge (example)*: email enqueued ∧ recorded in `outbound_mail` ∧ recipient within
    `Account.notif_*` ∧ idempotency key unused.
  - *ops-copilot (example)*: requested read produced a result ∧ no mutation attempted.
- **Honest outcome** — reuse `session_outcome.py::compute_outcome` (verify-derived, never
  prose) + `claim_mismatch` (catch the agent claiming success when the contract disagrees).
  Generalise `{aborted, incomplete, migrated}` → `{aborted, incomplete, accomplished}`.
- **Metric** — feed the existing `intervention_type` + `intervention_summary` + `omg
  surprises` rollup (generalised beyond migration).

## Runtime integration seams (no offline harness this round)

- **Cortex verify step** (#471): the deliberation loop's *Verify* calls **Grader B**;
  pass → conclude, fail → the findings re-enter as a fresh wall.
- **ActionGate** (#495): before an act-tool fires, the gate may require a **Grader A** pass
  (e.g. a drafted customer email clears groundedness + the judge rubric) — a guardrail.
- **SafetyGate** (existing): its verify-then-rollback *is* Grader B for the migration agent
  (`verify_migration` adopts the spine).
- **Surprises**: every outcome Verdict → `intervention_type` → `omg surprises`.

## Principles (lean / reuse / honest)

- **Reuse, don't add:** the router (judge), `adversarial.py`, the diagnosis models,
  `verify_migration` tiers, `session_outcome`, SQLite `intervention_type`. **No new store.**
- **Activatable:** LLM-based checks (judge, adversarial, groundedness) fire only when a key
  is present; deterministic checks (schema, outcome contract) always run.
- **Two-tier, fail-loud:** deterministic checks can be **hard**; LLM-based checks default to
  **advisory** (best-effort) and never silently hard-block — they log loud.
- **Honest by construction:** the outcome Verdict is the source of truth; prose claims are
  checked against it (`claim_mismatch`).

## Anti-scope (this round)
No offline eval harness, golden datasets, or CI regression scoring (chosen: runtime-only).
Not a metrics dashboard. The agents themselves stay kernel-phase (#496) — this is the
validation substrate they will consume.

## Workstreams
- **E1** — the `Verdict` spine (consolidate Finding/Confidence/Evidence/Provenance + hard/advisory).
- **E2** — Grader A response validators (schema + groundedness + adversarial, composed).
- **E3** — the activatable **JudgeCheck(rubric)** primitive (the one new piece).
- **E4** — Grader B agent-agnostic **OutcomeContract** + honest outcome + surprises.
- **E5** — runtime seams: wire into Cortex verify (#471), ActionGate (#495), SafetyGate.
