# Tools, Skills, and the cluster Tools-catalog (MCP)

> **STATUS: ASSESSMENT / DIRECTION — not the code today.** Grounds the cluster's
> use of *Tools* vs *Skills* vs *MCP* in Anthropic's published guidance
> ([writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents),
> [Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)).
> Refines the competence-model redesign (`euroblaze/ludo` #468–484) and the
> Cortex proposal ([`harness-brain.md`](./harness-brain.md)). Cross-cluster
> topology + vocabulary live in the workspace-root `CLAUDE.md`.

## 1. Three concepts, one line each

- **Tool** = a contract between a deterministic system and the non-deterministic
  agent — one callable primitive. *The hammer.* In LUDO: the `Tool` protocol in
  `ludo-agent/src/ludo/tools/`.
- **Skill** = a directory (`SKILL.md` + scripts/resources) packaging **procedural
  knowledge** — *when and how to compose tools toward a goal* — with progressive
  disclosure (name/description → body → bundled files on demand). *The carpentry
  know-how.* Open standard (Dec 2025), portable across Claude.ai / Code / SDK / API.
- **MCP** = the **transport** that exposes tools (and skills) across process /
  component boundaries. *The shared toolbox other workshops can borrow from.* This
  is what "a Tools-catalog visible to all components" actually is.

## 2. The decisive finding — only `ludo-agent` is agentic

| Component | Role | Agentic? | Tools | Skills |
|---|---|---|---|---|
| **ludo-agent** (`euroblaze/ludo`) | engine + worker; the Cortex | **Yes — the only agent** | ~37 (`src/ludo/tools/`) | the bespoke (dead) layer → re-found on the open standard |
| **ludo-apps** (`euroblaze/ludo-flywheel`) | frontends (Vue); backend retiring into gateway | No | — | — |
| **ludo-gateway** (`euroblaze/ludo-gateway`) | public edge API in front of the broker | No (proxy) | — (publishes the catalog) | — |
| **ludo-desktop** (`euroblaze/ludo-desktop`) | native SwiftUI client | No (UI) | — | — |
| **ludo-omg** (`euroblaze/ludo-omg`) | transport-only CLI | No (HTTP client) | — | — |

**Consequence:** "what tools/skills does each app need" resolves to — Tools and
Skills are a **`ludo-agent` concern**. Every other component is a deterministic
*client* that triggers the agent, or *transport* that carries invocations + events.
The cluster value is (a) getting the agent's tools/skills right and (b) **publishing
them as a discoverable catalog** so any future agentic surface reuses them instead of
re-implementing.

## 3. Tools — the agent's catalog (assessed against the guidance)

The current ~37 primitives are **capability-complete** for migration; the work is
*consolidation + namespacing + token-efficient returns + actionable errors* (the
article's levers — and exactly what the D-slice audit already names):

| Family | Tools | Verdict |
|---|---|---|
| Schema + data flow | `extract_from_odoo`, `extract_binary`, `load_to_odoo`, `load_binary`, `load_attachments`, `inspect_model`, `verify_migration` | keep — irreducible primitives |
| Cross-version intelligence | `discover_renames`, `discover_model_renames`, `discover_migration_order`, `create_blueprint`, `make_plan` | keep |
| FK mapping | `pin_xmlid`, `pin_by_natural_key`, `enrich_per_record_from_m2o`, `sync_pinned_fields`, `restore_workflow_states` | **consolidate** → `pin_record(strategy=…)` (D2) |
| Memory loop | `consult_memory`, `lookup_known_fix`, `query_recovery_sequences`, `record_finding`, `record_attempt`, `diagnose` | **consolidate** → `consult_memory(query, kind=…)` (D1); Cortex makes `lookup_known_fix` read-only + `diagnose` the spine (#471) |
| Mutation/workflow + sandbox | `invoke_workflow_action`, `grant_user_groups`; `read_file/glob/grep/web_fetch/write_to_fs`; module-port: `apply_patch`, `run_command`, `git_*`, `ast_*`, `install_module`, `run_module_tests` | keep — general primitives |

No new tool families needed for migration.

## 4. Skills — re-found on the open standard (refines #470)

The redesign retires ludo-agent's **bespoke skills implementation** (`manifest.json`
+ `trigger` predicates + `type_catalogue_min_evidence` + custom loader + the
memory→skill→core graduation ladder — zero organic graduations). That stands. But
"retire skills entirely" was too strong:

- **Dead** = the bespoke machinery. *Retire it.*
- **Keep the concept**, re-founded on the **Agent Skills open standard**
  (`SKILL.md` + progressive disclosure), used **only where genuine, recurring
  procedural know-how exists** — never as a speculative graduation target.

Real skill candidates (procedural know-how that composes §3 tools):
`migrate-workflow-driven-model` (load draft → advance), `computed-field-passthrough`
(write the depends, not the stored field), `port-odoo-module` (patch → install →
test → fix), `estimate-and-xray` (read-only scoping — feeds desktop's ScopePicker).
The **Cortex deliberation loop** itself is so central it belongs in **core** (the
system prompt), per the article's "if every agent needs it, it's not a skill."

The **per-agent skill catalog** — which skills each technical and business agent
needs, where they are stored/maintained, and how an agent loop calls them — is
worked out in [`agent-skills-catalog.md`](./agent-skills-catalog.md) (the
agent-agnostic `ludo.skills.SkillCatalog` loader + per-agent `skills/` homes).

## 5. The cluster Tools-catalog (MCP) — kernel-phase, published at the gateway

"A Tools-catalog visible to all components" = an **MCP surface**, namespaced
(`ludo_extract`, `ludo_verify`, …), **published through `ludo-gateway`** (the single
public door — which is absorbing the apps backend per `#96`). Seed already exists:
`omg tools list` + `register_builtin_tools`. Consumers (only if/when they go agentic):
a future **desktop local assistant**, **ludo-omg-as-MCP** (CLI-as-tools, like `gh`),
a future **apps support/sales agent**. This maps to the agent's existing kernel-phase
item *"MCP / ACP server surfaces"* — **post-autonomy, not now.**

## 6. Deltas to the open redesign

- **#470** reframed: retire the *bespoke* skills implementation; **re-found on the
  Agent Skills open standard** — don't drop skills as a concept.
- **new sub-issue (#470):** adopt the open standard; migrate the 2 real patterns.
- **new (kernel-phase):** publish the Tools-catalog as a namespaced MCP surface via
  `ludo-gateway` — deferred until after autonomy.
- **#472:** add the Tools/Skills/MCP definitions + "only `ludo-agent` is agentic"
  topology to the root `CLAUDE.md` (done in the harmonisation pass).
