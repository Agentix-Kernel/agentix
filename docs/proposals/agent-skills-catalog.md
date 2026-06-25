# Per-agent Skills — catalog, storage, and invocation across the cluster

> **STATUS: DIRECTION — converged design, partial scaffold in tree.** Builds on
> the activatable multi-agent cluster ([`agentic-cluster-a2a.md`](./agentic-cluster-a2a.md)
> — agent map, NATS trust zones, ActionGate) and the Tools/Skills/MCP assessment
> ([`tools-skills-mcp.md`](./tools-skills-mcp.md) — Skills re-founded on the Agent
> Skills open standard). Answers: **which skills does each technical and business
> agent need, where are they stored and maintained, and how does an agent
> loop/session call them.** The server-side business/ops agents are **W4 /
> kernel-phase** — this names their skill shape; it does not ship runnable agents.

## 1. Agent inventory — technical vs business

From the agent map. Skills are a **server-side, LUDO-keyed** concern only; client
(BYO-key, EDGE) agents are read/local/advisory and carry no server skills — they
get real capability by A2A request to a server agent.

| Agent | Class | NATS zone | Status | Per-agent skills home |
|---|---|---|---|---|
| migration agent | technical | INTERNAL (no PII) | live | `skills/` |
| ops/admin copilot | technical-ops | CONTROL (PII-cleared) | W4, deferred | `agents/ops_copilot/skills/` |
| concierge | business | CONTROL (PII-cleared) | W4, deferred | `agents/concierge/skills/` |
| `omg` / WMD / desktop client agents | client/advisory | EDGE (BYO-key) | deferred | none server-side |

New server agents are **kernel-phase processes built on this repo's harness-as-
kernel**, so they live here under `agents/<name>/` — honoring both "only
`ludo-agent` is agentic" and "per-agent skills co-located with each process."

## 2. Per-agent skill catalog

Each skill is **procedural know-how composing tools toward a goal** — never a
per-customer or per-quirk artifact. *(scaffold)* = a forward-reference `SKILL.md`
stub in tree; *(live)* = active migration skill.

### Migration agent (technical) — composes the ~37 migration primitives
- `computed-field-passthrough` *(live)* — write the depends, not the stored field.
- `state-locked-workflow-advance` *(live)* — load draft → advance workflow.
- `migrate-workflow-driven-model` *(scaffold)* — the general load-draft→advance shape.
- `port-odoo-module` *(scaffold)* — patch → install → test → fix (module-port mode).
- `estimate-and-xray` *(scaffold)* — read-only scope + cost; feeds the desktop ScopePicker.

### ops/admin copilot (technical-ops) — broad read, act gated via A2A
- `triage-stuck-migration` *(scaffold)* — diagnose a stall from session/job/event
  state; recommend or (gated) A2A-trigger resume/rollback.
- `queue-capacity-review` *(scaffold)* — JetStream backlog + slot balance.
- `vault-access-audit` *(scaffold)* — anomalous credential-access patterns.
- `pricing-config-sanity` *(scaffold)* — vet a pricing-config edit before apply.

### concierge (business) — read customer/commerce state, gated comms
- `migration-status-briefing` *(scaffold)* — plain-language status from Contract B events.
- `schedule-and-nudge` *(scaffold)* — gated email/SMS + scheduling (the act path).
- `onboarding-walkthrough` *(scaffold)* — vault → estimate → approve-and-pay.
- `billing-question-handler` *(scaffold)* — invoices / subscription / discounts (read-only).
- `support-triage` *(scaffold)* — classify, route, draft a reply.
- `referral-followup` *(scaffold)* — convert share/conversion events into gated nudges.

**Prerequisite, stated plainly:** every business/ops skill composes **act-tools
that do not exist yet** (email/SMS/schedule, commerce + state reads) plus the
**`ActionGate`** middleware (rate-limit · quiet-hours · prefs · idempotency ·
audit). Those are W3/W4 work in `agentic-cluster-a2a.md`. The scaffolds name the
procedural shape so the catalog and this design are concrete; they are not
runnable code.

## 3. Storage & maintenance

- **Storage — per-agent `skills/`.** Each agent process owns its own dir. The
  migration agent keeps the incumbent top-level `skills/`; new agents get
  `agents/<name>/skills/`. The per-agent partition also makes the **trust-zone
  boundary legible**: a CONTROL-zone concierge skill may reference PII-bearing
  comms; an INTERNAL-zone migration skill must not, and they never share a dir.
- **Format — the Agent Skills open standard.** A bundle is a directory with a
  `SKILL.md` carrying YAML frontmatter (`name`, `description`, optional
  `allowed-tools`), a body of procedural know-how, and optional bundled resources
  + a `tool.py` for skill-scoped primitives. This **retires the bespoke
  `manifest.json` + trigger-predicate machinery** as the selection mechanism
  (`tools-skills-mcp.md` §4). `manifest.json` survives only as a backward-compat
  carrier for the two live migration skills (which also keep their recon-phase
  trigger wiring untouched).
- **Maintenance — the maturation pipeline, per agent.** `findings → memory → skill
  → core` generalizes: each agent has its own memory substrate (migration's
  `memory/`; the business agents' per-customer system-of-record stays the
  control-plane DB). The first arrow (findings→memory) stays automatic via
  `MemoryMaintainMiddleware`; memory→skill→core stay operator-reviewed PRs between
  deployments. **No speculative skills** — the scaffolds here are explicitly
  forward-reference, not graduation targets; a real skill earns its place only on
  cross-customer evidence (≥3 customers, ≥2 pairs).

## 4. Invocation by agent loops/sessions

- **Generalized loader — `ludo.skills.SkillCatalog`** (new, agent-agnostic; in
  tree). An agent process points it at *its own* `skills_root`. At session start
  it surfaces each bundle's `(name, description)` cheaply (`describe()`); the
  Cortex pulls the full `SKILL.md` body on demand via `read_file` (**progressive
  disclosure**) — model-driven selection from descriptions, replacing hard
  trigger-predicate gating. Skill-scoped `tool.py` tools register into the agent's
  `ToolRegistry` on activation, delegating to the incumbent
  `register_activated_skills` so there is exactly one tool-import path.
- **Migration agent (live path) — unchanged signature.**
  `run_agent_migration(activated_skill_names, skills_root)` and the recon-phase
  trigger evaluator (`core/reconnaissance.py`) stay intact; the catalog is
  additive and the two live skills still activate on a `target_version=V18` recon.
- **Business/ops agents (deferred path) — same lib, different trigger source.**
  The session is woken by an **inbound A2A request / customer event** (not a
  version pair); the request intent + customer context drive which `SKILL.md` body
  the Cortex reads. Same `ToolRegistry` + middleware chain, with `ActionGate`
  wrapping act-tools so a BYO-key EDGE client can never reach them.

## 5. What this change ships now vs defers

**Now (in tree):** the agent-agnostic `SkillCatalog`; three forward-reference
migration skill stubs; the `agents/{concierge,ops_copilot}/skills/` scaffolds;
this doc. The incumbent migration loader, its tests, and the two live skills are
untouched.

**Deferred (W1–W4 in `agentic-cluster-a2a.md`):** the business/ops act-tool
catalogs, the `ActionGate` middleware, the NATS trust-zone substrate, and the
concierge / ops-copilot processes themselves. No claim here that any business or
ops agent is runnable today.
