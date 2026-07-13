# Skills

**Status:** living doc · **Scope:** Agentix kernel `[K]` (app-agnostic), with a
labelled reference-cluster DIRECTION part

**Single source of truth for skills in `docs/`.** Sections 1–6 document the landed
kernel skill subsystem (code: `src/agentix/skills/`); sections 7–9 are **DIRECTION**
— converged design, not the code today — consolidated from the retired proposal
`proposals/agent-skills-catalog.md`. Tools and the four calling verbs are canonical
in [`tools.md`](tools.md) (§9–10 there cover the *consult* and *compile* verbs,
which act on skills). Tracking: [euroblaze/ludo #470](https://github.com/euroblaze/ludo/issues/470)
(competence-model redesign), #498/#513/#514 (catalog implementation).

---

## 1. What a Skill is — the open standard

A **Skill** is a directory (`SKILL.md` + optional scripts/resources) packaging
**procedural knowledge** — *when and how to compose tools toward a goal* — with
progressive disclosure: name/description surfaced cheaply, full body pulled on
demand, bundled files only when the body references them. *The carpentry know-how*
to a tool's *hammer*. This is the Agent Skills **open standard** (Dec 2025),
portable across Claude.ai / Code / SDK / API; Anthropic guidance:
[Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills).

Two things are easy to conflate and must not be:

- **Dead** = the bespoke selection machinery (`manifest.json` + trigger predicates
  + evidence thresholds + the memory→skill→core graduation ladder — zero organic
  graduations). Retiring per #470. It survives in the kernel only as the
  back-compat loader (§5).
- **Kept** = the concept, re-founded on the open standard, used **only where
  genuine, recurring procedural know-how exists** — never as a speculative
  graduation target.

And per the guidance's "if every agent needs it, it's not a skill": the Cortex
deliberation loop itself belongs in **core** (the system prompt), not in a skill.

## 2. Bundle layout

A bundle is one directory under the agent's `skills_root`:

```
skills/<name>/
  SKILL.md          # required (open standard): YAML frontmatter + procedure body
  tool.py           # optional: register(registry) for skill-scoped tools
  manifest.json     # legacy carrier (v2 schema) — retiring as selection mechanism
  <resources…>      # optional files the body references
```

- `SKILL.md` frontmatter: `name`, `description` (drive the cheap surfacing),
  optional `allowed-tools`.  Extended A2A fields (optional): `id`, `tags`,
  `examples`, `input_modes`, `output_modes` — parsed by `SkillCatalog` into
  `SkillBundle` and projected to `AgentSkill` via `to_agent_skill()`.
  The body is the procedure the model reads on consult.
- `tool.py` exports `register(registry)`; the loader imports it and hands it the
  registry so the bundle can add skill-scoped tools (§6). Doctrine-only bundles
  (no tools) are the common case.
- Directories whose name starts with `_` are **reference templates** — discovered
  but excluded from `describe()` and `consult_skill` (not real capabilities).
- The reference app's fuller bundle spec (manifest v2 fields, trigger predicates)
  is `ludo-agent/skills/SCHEMA.md` — incumbent, not the standard.

## 3. `SkillCatalog` — discovery + progressive disclosure

`skills/catalog.py`.  The agent-agnostic reader: takes `roots: Path | str |
Sequence[Path | str]`.  **Multi-root**: bundles are discovered across all roots;
first-root-wins on name clash (logs `skills.name_clash` warning).

- `bundles()` — a directory is a bundle when it carries a `SKILL.md` (open
  standard) or a `manifest.json` (legacy). Frontmatter wins over manifest for
  `name`/`description`/`allowed-tools`.  A2A frontmatter fields (`id`, `tags`,
  `examples`, `input_modes`, `output_modes`) populate `SkillBundle`.  Best-effort:
  unreadable bundles log a warning and are skipped.
- `describe()` — `(name, description, skill_md_path)` rows for **session-start
  surfacing**.
- `activate(names, registry)` — registers skill-scoped tools across all roots by
  delegating to the incumbent loader (§5).
- `SkillBundle.to_agent_skill()` — project into an A2A v1.0 `AgentSkill`; used
  by driver `publish_agent_card()` to build the card's `skills` list.

## 4. `consult_skill` — the consult tier

`skills/consult_skill.py`. A registered read-only tool (the *consult* verb of
[`tools.md` §9](tools.md)): the model calls `consult_skill(name=…)` when a listed
skill's description matches the situation, and gets the full `SKILL.md` body.

- Why a dedicated tool: `read_file` is sandboxed to the task's source/output
  roots and **cannot reach `skills/`**. `consult_skill` reads from the agent's own
  catalog root (`ToolContext.skills_root`).
- Bodies are small (~5 KB typical); capped defensively at 64 KB with a
  `truncated` flag.
- Unknown name → actionable error listing the available skill names (reference
  templates excluded).

## 5. The incumbent manifest loader — retiring

`skills/loader.py`. The bespoke pre-standard machinery, kept for back-compat and
as the single tool-import path:

- `load_skills(root, registry)` — scan `*/manifest.json`, register every bundle
  that validates; failures log + skip (best-effort, the core runs without them);
  one aggregate `skills.load_summary` log line.
- `list_skill_manifests(root)` — manifests only, **no imports/registration**; used
  by a recon phase to evaluate trigger predicates before deciding activation.
- `register_activated_skills(root, names, registry)` — import + register `tool.py`
  tools for the activated names only; doctrine-only skills count as activated with
  zero tools. Not idempotent per registry — pass a fresh registry per session.
- Manifest v2: `name` + `version` required; `tools` optional; `customer` accepted
  with a deprecation warning (skills are general, never per-customer); missing
  `trigger` warns for production bundles.

**Status:** retiring as the *selection* mechanism (#470) — selection moves to
model-driven `describe()` + `consult_skill` (§3–4). `manifest.json` survives only
as a carrier for live legacy bundles and their trigger wiring.

## 6. Registration + context plumbing

- Skill tools enter the registry through `ToolRegistry.try_register` semantics
  (see [`tools.md` §2](tools.md)): lenient — log + skip on failure, one broken
  bundle must not take down the service — and a skill can never silently shadow a
  builtin (`ToolConflict`).
- `ToolContext` carries the skill state (`tools/base.py`):
  `activated_skill_names` (bundles whose triggers matched, threaded into each
  per-step registry) and `skills_root: str | list[str]` (where `consult_skill`
  reads from; default `"skills"`).  Pass a list to expose multiple catalogs.

---

*Everything below is DIRECTION — converged design from the reference cluster
(absorbed from the retired `proposals/agent-skills-catalog.md`), not the code
today. Cluster context: `ludo-agent/docs/proposals/agentic-cluster-a2a.md`
(agent map, NATS trust zones, ActionGate). The server-side business/ops agents are
W4 / kernel-phase — this names their skill shape; it does not ship runnable agents.*

## 7. Per-agent skills across a cluster

Skills are a **server-side, operator-keyed** concern only; client (BYO-key, EDGE)
agents are read/local/advisory and carry no server skills — they get real
capability by A2A request to a server agent.

Reference-cluster inventory:

| Agent | Class | NATS zone | Status | Per-agent skills home |
|---|---|---|---|---|
| migration agent | technical | INTERNAL (no PII) | live | `skills/` |
| ops/admin copilot | technical-ops | CONTROL (PII-cleared) | W4, deferred | `agents/ops_copilot/skills/` |
| concierge | business | CONTROL (PII-cleared) | W4, deferred | `agents/concierge/skills/` |
| client agents (CLI / desktop) | client/advisory | EDGE (BYO-key) | deferred | none server-side |

New server agents are kernel-phase processes built on the same harness, living
under `agents/<name>/` — per-agent skills co-located with each process.

Each skill is procedural know-how composing tools toward a goal — never a
per-customer or per-quirk artifact. The reference catalogs (*(live)* = active,
*(scaffold)* = forward-reference `SKILL.md` stub):

- **Migration agent (technical)** — composes the ~37 migration primitives:
  `computed-field-passthrough` *(live)*, `state-locked-workflow-advance` *(live)*,
  `migrate-workflow-driven-model`, `port-odoo-module`, `estimate-and-xray`
  *(scaffolds)*.
- **ops/admin copilot (technical-ops)** — broad read, act gated via A2A:
  `triage-stuck-migration`, `queue-capacity-review`, `vault-access-audit`,
  `pricing-config-sanity` *(all scaffolds)*.
- **concierge (business)** — read customer/commerce state, gated comms:
  `migration-status-briefing`, `schedule-and-nudge`, `onboarding-walkthrough`,
  `billing-question-handler`, `support-triage`, `referral-followup`
  *(all scaffolds)*.

**Prerequisite, stated plainly:** every business/ops skill composes act-tools that
do not exist yet (email/SMS/schedule, commerce + state reads) plus the
**ActionGate** middleware (rate-limit · quiet-hours · prefs · idempotency ·
audit) — W3/W4 work in `agentic-cluster-a2a.md`. The scaffolds name the procedural
shape; they are not runnable code.

## 8. Storage & maintenance

- **Storage — per-agent `skills/`.** Each agent process owns its own dir. The
  per-agent partition also makes the **trust-zone boundary legible**: a
  CONTROL-zone skill may reference PII-bearing comms; an INTERNAL-zone skill must
  not, and they never share a dir.
- **Format — the open standard** (§2). This retires the bespoke
  `manifest.json` + trigger-predicate machinery as the selection mechanism;
  `manifest.json` survives only as a back-compat carrier for live legacy bundles
  (which keep their recon-phase trigger wiring untouched).
- **Maintenance — operator-reviewed, evidence-gated.** Findings→memory stays
  automatic; memory→skill and skill→core are operator-reviewed PRs between
  deployments. **No speculative skills** — a real skill earns its place only on
  cross-customer evidence (reference bar: ≥3 customers, ≥2 version pairs);
  scaffolds are explicitly forward-reference, not graduation targets.

## 9. Invocation by agent loops

- **Generalized path** — an agent points `SkillCatalog` at its own `skills_root`;
  session start surfaces `describe()` rows into context; the model pulls a full
  body via `consult_skill` (progressive disclosure) — model-driven selection from
  descriptions, replacing hard trigger-predicate gating. Skill-scoped `tool.py`
  tools register on activation through the one tool-import path (§3/§5).
- **Reference live path — unchanged signature.** The migration agent's
  `run_agent_migration(activated_skill_names, skills_root)` and its recon-phase
  trigger evaluator stay intact; the catalog is additive.
- **Business/ops agents (deferred) — same lib, different trigger source.** The
  session is woken by an inbound A2A request / customer event (not a version
  pair); the request intent + customer context drive which body the model reads.
  Same `ToolRegistry` + middleware chain, with ActionGate wrapping act-tools so a
  BYO-key EDGE client can never reach them.

**Shipped now:** the agent-agnostic `SkillCatalog` + `consult_skill`; the
reference scaffolds. **Deferred (W1–W4):** business/ops act-tool catalogs, the
ActionGate middleware, the NATS trust-zone substrate, and the concierge /
ops-copilot processes themselves.
