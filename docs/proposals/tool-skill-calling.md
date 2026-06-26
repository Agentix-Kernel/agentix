# Tool & Skill calling — the four verbs and the Consult↔Compile lifecycle

> **STATUS: DIRECTION — converged design, not the code today.** Cardinal tracking issue
> [euroblaze/ludo #503](https://github.com/euroblaze/ludo/issues/503); sub-issues #499–502.
> Builds on [`tools-skills-mcp.md`](./tools-skills-mcp.md) (Tools/Skills/MCP grounding),
> [`agent-skills-catalog.md`](./agent-skills-catalog.md) (per-agent skills), and
> [`agentic-cluster-a2a.md`](./agentic-cluster-a2a.md) (A2A, trust zones). Cross-cluster
> vocabulary lives in the `ludo-init/CLAUDE.md`.

## 1. Four calling verbs

How a capability gets invoked has, on inspection, **four** distinct primitives — not one:

| Verb | What it is | Plane | Cost |
|---|---|---|---|
| **call** a tool | one in-process primitive the LLM invokes (the `Tool` protocol) | vertical, in-process | one tool dispatch |
| **consult** a skill | pull procedural know-how into context on demand (`consult_skill` → `SKILL.md` body) | context, progressive disclosure | an LLM turn |
| **compile** a skill | lift its strategy into deterministic config the body executes | ahead-of-time | **none at runtime** |
| **delegate** | hand the work to another agent over A2A (NATS) | horizontal, cross-process | a job round-trip |

The earlier mental model ("surface skills → LLM consults → composes tools → results feed
back") is only the **consult** verb. The framework names all four and the lifecycle that
moves a strategy between them. Sub-issues: capability levels [#500], selection [#501],
delegate/A2A [#502]. This doc develops **consult↔compile** [#499].

## 2. The Consult↔Compile lifecycle (the spine)

**The decisive finding: LUDO already has the two end-tiers** — they were just never named
as one lifecycle. A surprise during a drain falls through a **cost-ordered cascade**:

| Tier | Mechanism (today) | LLM? |
|---|---|---|
| **S3 Compiled** | `build_remediation_router` / `apply_known_fix` (`actions/migrate.py:874`) matches an `error_catalogue.yaml` recipe and applies it via `update_rename_map` (drop) / `pin_by_natural_key` / `enrich_per_record_from_m2o` | none |
| **S1/S2 Consult** | router declines (`None`) → `run_compose_drain`'s `compose_recovery` (`migrate.py:1042`) → `run_agent_migration`; skills surfaced + `consult_skill` body | guided turn |
| **S0 Novel** | no recipe, no skill → reason from scratch + `record_finding` | full reasoning |

`build_remediation_router` declines to the agent **only when the recipe needs judgment**
— it exists precisely "so the LLM brain stays asleep for surprises that aren't surprises."
That is the compiled tier, already load-bearing.

**The lifecycle = a managed descent S0 → S1 → S3:**

- A novel surprise (S0) → finding → reconciled into the wiki → authored as a **skill** (now
  S1, consultable). *(This arrow exists: the maturation pipeline.)*
- A skill whose runtime application is **provably invariant** across N customers/pairs →
  **compiled** into an `error_catalogue.yaml` recipe (+ rename-map rule) → thereafter
  handled at **S3** deterministically. *(This is the missing arrow.)*

The system's intelligence is the share of traffic the **S3** tier absorbs. Trending it up
is a measurable form of the autonomy bar's *"surprises per customer → 0"* — a concrete
read on "the army gets better between campaigns."

## 3. The gap to close

1. **Single-source the spec and the impl.** Today a strategy lives as *three* artifacts —
   (i) the hand-coded `recipe.action` branches in `build_remediation_router._apply_recipe`
   (`migrate.py:909/925/943` — drop / pin / enrich), (ii) the `error_catalogue.yaml` rows,
   and (iii) the skill prose — which drift. Give a skill a **declarative remediation
   block** (`{tool, params, success_predicate}`, machine-readable) alongside the prose.
   **Compilation = lifting that block into a router recipe**, so one source feeds both
   consult and compile. The prose stays as the human spec + the decline-fallback.
2. **Trace-based compile-readiness.** Each successful consult already emits a trajectory
   (TrajectoryCapture) + `record_attempt`/`diagnose`. Score **invariance** across traces
   (same tool sequence + same param-derivation); when it crosses a threshold (analogous to
   `promotion_threshold`), flag the skill a **compile candidate** for operator review. This
   reframes `skill→core` as *emit a deterministic executor + demote the skill to
   evidence/fallback* — not "delete."
3. **Control metric.** Track the S3/S1/S0 share, derivable from existing Contract B events.

## 4. Async/NATS leverage — upside without new infrastructure

The lifecycle's core move (**consult → compile**) is the same move as
**expensive-serial-LLM → cheap-parallel-idempotent-job** — exactly what the NATS substrate
already optimizes. We compose existing rails, not build new ones:

- **The compiled tier is already broker-parallel.** S3 work is deterministic + idempotent
  (the xmlid census), so it can run as independent jobs fanned out by **queue groups across
  replicas** — no orchestration code. Moving a strategy consult→compile also moves it
  serial→parallel for free.
- **Consult can ride the queue instead of blocking.** `compose_recovery` calls
  `run_agent_migration` **inline** today. The offload pieces already exist — the
  `JobType→handler` registry (`worker/registry.py:221`), consume/ack, Contract B events,
  and `continue_on_escalation` (`migrate.py:1225`). Routed through a subject, one model's
  LLM recovery never stalls the other 99%, and recoveries parallelize.
- **Retry/crash-resilience is free** — at-least-once + idempotent execution → a consult
  that dies mid-recovery redelivers with no duplicate writes.
- **Compile-readiness rides the session-close hook** (TrajectoryCapture + WikiMaintain
  reconcile→promote on `session_end`) — more work on an existing event, not a new scheduler.
- **The cascade metric is event-stream observability** (`job_completed`/`safety_event`/
  `turn_*`) — read the stream, don't add counters.
- **No registry service** — reuse the JobType registry as the capability registry; the
  subject space *is* the registry.

*Honest caveat: not literally zero new code (tag events with a tier; route the consult
subject) — but **no new infrastructure or services.***

## 5. Code-saving (CRIE) — the framework shrinks the catalog

A **consolidation**, not an accretion:

- **One declarative recipe collapses 3 paths → 1.** The generic `{tool, params,
  success_predicate}` executed over the **existing `Tool` protocol** replaces the if/elif
  ladder in `_apply_recipe` with table-driven dispatch, and removes catalogue↔skill drift.
- **Named tool consolidations (already flagged tech-debt).** `pin_xmlid` /
  `pin_by_natural_key` / `enrich_per_record_from_m2o` / `sync_pinned_fields` /
  `restore_workflow_states` → `pin_record(strategy=…)` (D2); `consult_wiki` /
  `lookup_known_fix` / `query_recovery_sequences` → `consult_knowledge(query, kind=…)`
  (D1). ~7 tool classes → 2.
- **Retire the bespoke skills machinery** — `manifest.json` trigger predicates,
  `type_catalogue_min_evidence`, `evaluate_skill_triggers`/`_trigger_passes` →
  the single open-standard `SkillCatalog` loader.
- **Reuse, don't add, the registry** — avoids a registry service the naive design grows.

**The unifying point:** the framework's central artifact — a declarative, Tool-protocol-
executed recipe — is *simultaneously* what rides the NATS rails (idempotent, queueable)
**and** what collapses the redundant code paths. The async upside and the CRIE upside are
**one lever seen from two sides.**

## 6. First increments (under #499)

1. **Consult tier wiring** — surface `SkillCatalog.describe()` into the agent's context at
   session start + add an always-on `consult_skill(name)` builtin (reads the body from the
   real skills root; `read_file` is sandboxed and can't). Covers both the standalone agent
   path and compose-on-surprise (which delegates to `run_agent_migration`).
2. **The compiler link** — declarative remediation block on skills → router recipe; trace
   invariance scoring → compile-candidate flag at session close.
