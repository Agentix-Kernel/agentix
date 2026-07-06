# Agentix — the reusable, app-agnostic agentic-app kernel

A one-page tour of the kernel's surface. Each line is deliberately terse; see the
per-topic docs (`session.md`, `context.md`, `isolation.md`, the contracts, and the
component inventory in agentix#1) for detail.

**What it is.** The frozen API and principles for building agent apps, distilled from a production system. A deterministic body that wakes an LLM only on surprise. Apps supply domain tools, prompts and memory sources; the kernel supplies everything else. A strict `[K]` kernel / `[A]` app split keeps domain terms out of the core, enforced by a purity gate.

**Engine and dispatch.** A turn engine runs an ordered middleware chain around each step; the agent dispatcher owns the LLM loop — build request, call, dispatch tool calls, append results. Messages are an opaque list the engine snapshots per turn.

**Cortex-on-surprise.** The deterministic path handles the routine; the model is invoked only when something is unexpected. Surprises descend a cost-ordered cascade — compiled recipe → consult skill → novel reasoning — so the cheapest competent path wins.

**Four calling verbs.** *call* a tool (in-process), *consult* a skill (pull its body on demand), *compile* a skill into a deterministic recipe (no LLM at runtime), *delegate* to another agent over A2A.

**Tools.** A registry with provider-neutral spec conversion. Always-on read-only primitives (read, glob, grep, fetch) plus opt-in mutating primitives (write, patch, shell, git). Consolidate, namespace, token-efficient returns, actionable errors.

**Skills.** The Agent Skills open standard, loaded by an agent-agnostic catalog. Progressive disclosure — cheap name and description at session start, full body on demand — so the window stays lean.

**Working memory.** A structured tried / failed / learned log that survives context compression, auto-recorded on tool failure and on recoveries that overturn a blocked path, and rendered into a system message every turn.

**Sessions.** The checkpoint-first, resumable unit of a run: create, save, resume-from. Operational state in SQLite, full state blob in object storage. App scope is opaque `app_meta`. Sessions carry a control-plane binding and a parent link for streaming and delegation hierarchy.

**Context management.** One owner of the model window — assemble, budget, compress, evict by priority tier (guardrails > goal > working set > retrieved memory > history), with a per-turn X-ray of what entered and why.

**Token economics.** Per-session and per-account budget ceilings; cost recorded at each LLM call, not after the fact. Pluggable compression collapses old tool results before the budget is breached.

**Storage.** An async SQLite store (WAL, busy-timeout, FTS5 search, schema-versioned migrations) for operational state, and an object store for checkpoints and bulk data — data and memory never cross.

**Isolation and concurrency.** One session = one context = one task-tree root; only distilled context crosses any boundary. Per-task cost and DB scoping, structured concurrency, a session lease with an orphan reaper, and trust-zone NATS accounts (edge / control / internal), deny-by-default.

**Safety and guardrails.** ActionGate on mutating tools — rate-limit, quiet-hours, idempotency, audit. Loop detection and recorded safety events.

**Memory tiers.** Three classifications — Transient (one run), Episodic (per-tenant and per-context), Learnings (general) — with verbs to reconcile a finding into a rule and promote it on cross-case evidence.

**A2A over NATS.** Capability subjects as the registry, an agent card as the INFO reply, the *delegate* verb, and activatable key-gated agents with a deterministic fallback when no key is present.

**Evaluation.** A Verdict spine grading both responses and outcomes, with an activatable LLM judge; honest outcome labels derived from verification rather than the agent's own claim.

**Contracts and codegen.** Versioned wire contracts as the single source of truth, generating Python, TypeScript and Swift, with cross-repo drift guards so consumers never hand-maintain parallel copies.
