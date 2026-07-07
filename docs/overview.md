# Agentix — the reusable kernel for building AI agents

### What it is.

- The frozen, app-agnostic API and principles for building agentic applications.
- A deterministic body that wakes an LLM only on escalation.
- Apps supply domain tools, prompts and memory sources; the kernel supplies everything else.
- A strict `[K]` kernel / `[A]` app split keeps domain terms out of the core, enforced by a purity gate.

### Engine and dispatch.

- A turn engine runs an ordered middleware chain around each step;
- the agent dispatcher owns the LLM loop — build request, call, dispatch tool calls, append results.
- Messages are an opaque list the engine snapshots per turn.

### Cognitive escalation.

- An *escalation* happens when an automated step cannot prove its result is correct (in the reference app: rows failed to load, a verification failed, or values changed during transfer).
- The deterministic body handles the routine; an escalation is the only event that wakes the model (the *Cortex*).
- Escalations descend the escalation ladder — compiled recipe (model stays asleep) → consult skill → novel reasoning — so the cheapest competent path wins; the loop then re-runs the step to re-prove it.
- If the budget is spent before the step proves clean, the agent performs an *operator handoff* (distinct term: escalation = body wakes the model; handoff = agent gives up to a human).
- The share of escalations absorbed at the compiled tier is the system's intelligence; the product metric is *escalations/customer → 0*.
- Detail: `docs/tools.md` (the ladder), `proposals/eval-validation.md` (the metric rollup); reference implementation `ludo-agent/src/ludo/core/compose_loop.py`.

### Four calling verbs.

The caller is always the model, woken by an escalation. The four verbs are the four ways it can get work done.

- *call* a tool — do one thing now, in-process.
- *consult* a skill — pull the full know-how text into context, then act on its steps.
- *compile* a skill — turn know-how into a deterministic recipe; next time the body applies it and the model stays asleep.
- *delegate* — hand the task to another agent over A2A.

Detail and worked examples: `docs/tools.md`.

### Tools.

- A registry with provider-neutral spec conversion.
- Always-on read-only primitives (read, glob, grep, fetch) plus opt-in mutating primitives (write, patch, shell, git). Consolidate, namespace, token-efficient returns, actionable errors.
- Detail: `docs/tools.md` (contract, registry, sandbox, safety gate, dispatch flow).

### Skills.

- The Agent Skills open standard, loaded by an agent-agnostic catalog.
- Progressive disclosure — cheap name and description at session start, full body on demand — so the window stays lean.

### Working memory.

A structured tried / failed / learned log that survives context compression, auto-recorded on tool failure and on recoveries that overturn a blocked path, and rendered into a system message every turn.

### Sessions. 

- The checkpoint-first, resumable unit of a run: create, save, resume-from. 
- Operational state in SQLite, full state blob in object storage.
- App scope is opaque `app_meta`.
- Sessions carry a control-plane binding and a parent link for streaming and delegation hierarchy.

### Context management.

- One owner of the model window — assemble, budget, compress, evict by priority tier (guardrails > goal > working set > retrieved memory > history), with a per-turn *window report* of what entered and why.

### Budgets (token economics).

- Per-session and per-account spending ceilings, in money; cost is recorded at each LLM call, not after the fact.
- **Safety**: no human approves anything mid-run, so the budget is what ends a hopeless retry loop — when it runs out, the agent stops and hands off honestly instead of trying forever.
- **Economics**: tokens cost money. The account ceiling stops one expensive customer from eating the margin of the others; the control plane enforces it and gives each job the remaining headroom.
- **Design pressure**: every escalation has a price, so the system is pushed to solve problems the cheap way and to learn — it gets smarter by learning, not by spending more.
- A budget caps how often the model is woken, never how hard it thinks in a turn. Ceilings are policy: set per account, or lifted entirely.
- The model-window budget is a separate thing — see Context management above.

### Storage. 
- An async SQLite store (WAL, busy-timeout, FTS5 search, schema-versioned migrations) for operational state, and 
- an object store for checkpoints and bulk data
- Data and memory never cross.

### Isolation and concurrency.

- One session = one context = one task-tree root;
- Only distilled context crosses any boundary.
- Per-task cost and DB scoping, structured concurrency, a session lease with an orphan reaper, and trust-zone NATS accounts (edge / control / internal), deny-by-default.

### Safety and guardrails.

- ActionGate on mutating tools — rate-limit, quiet-hours, idempotency, audit.
- Loop detection and recorded safety events.

### Memory tiers.

Three classifications 
- Transient (one run — the working-memory log above), 
- Episodic (per-tenant and per-context),
- Learnings (general)

.. with verbs to reconcile a finding into a rule and promote it on cross-case evidence.

### A2A over NATS.

- Capability subjects as the registry,
- an agent card as the INFO reply,
- the *delegate* verb, and
- activatable key-gated agents with a deterministic fallback when no key is present.

### Evaluation.

- A Verdict spine grading both responses and outcomes, with an activatable LLM judge;
- honest outcome labels derived from verification rather than the agent's (or the Cortex/LLM's) own claim.

**Contracts and codegen.** 

- Versioned wire contracts as the single source of truth, generating Python, TypeScript and Swift, with cross-repo drift guards so consumers never hand-maintain parallel copies.
