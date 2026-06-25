# CLAUDE.md — LUDO workspace (cross-repo hub)

This is the **overarching hub** for the LUDO product cluster: the overall cluster
description, the **shared vocabulary**, and the **agentic surface** (Tools / Skills /
MCP). It is deliberately thin on repo specifics — **each repo's own CLAUDE.md is
authoritative for that repo**; this file points to them. Read this first to know
*which repo owns what*, then defer to the repo file for detail.

## What this directory is

`/Users/ashant/s_/ludo` is a **workspace**, not a git repo. It holds several
independently-versioned repos being converged into one product (LUDO — autonomous
Odoo cross-version migration):

| Folder | GitHub | Role | Repo CLAUDE.md owns |
|---|---|---|---|
| `ludo-agent/` | `euroblaze/ludo` | The migration **engine + worker** — internal-only, no public port. 3 stores, ~37 tools, the **Cortex** (LLM). **The only agentic component.** | autonomy bar, locked decisions, tools/skills, the Cortex, the three stores |
| `ludo-gateway/` | `euroblaze/ludo-gateway` | The **public control-plane edge API** — the *single public door* in front of the broker for all clients. Terminates auth/tenancy/vault, turns commands into jobs, projects events as resumable SSE. **Absorbing the apps backend** (epic `flywheel#96`). | edge API, auth/tenancy/vault, Contract A, broker seam, commerce |
| `ludo-webapps/` | `euroblaze/ludo-flywheel` | The **product frontends**: 3 **Vue 3 + Vite** apps (public, portal, superadmin). Its FastAPI backend is **retiring into the gateway**; post-cutover apps = frontends-only. | frontends, locale, Contract A consumption |
| `ludo-cli/` | `euroblaze/ludo-omg` | **Transport-only CLI** client (like `gh`/`kubectl`) — no engine, no creds; talks to a deployment over the public API. | CLI commands, client transport |
| `ludo-desktop/` | `euroblaze/ludo-desktop` | Native **SwiftUI desktop client** (macOS; Windows TBD) — thin client over the public API. | desktop UI, native auth (PKCE) |

More clients (web / mobile / **WMD**) will join; all are thin clients of the gateway.
The user's global `~/.claude/CLAUDE.md` also applies, but where it conflicts with
reality (see "Drift") the repo is authoritative.

## Licensing

Two tiers. **Source-available** (BSL 1.1 → Apache-2.0 at the 4-year change date — *not* OSI
open-source) for the engine, the gateway edge, and the clients; **closed/proprietary** for the
product frontends (`ludo-webapps`). Full policy: [`docs/licensing-policy.md`](docs/licensing-policy.md).

| Repo | License |
|---|---|
| `ludo-agent` | BSL 1.1 → Apache-2.0 · Licensor: wapsol (labs) gmbh |
| `ludo-webapps` (flywheel) | Proprietary — all rights reserved (© wapsol (labs) gmbh) |
| `ludo-gateway` | BSL 1.1 → Apache-2.0 · Licensor: wapsol (labs) gmbh |
| `ludo-cli` | BSL 1.1 → Apache-2.0 · Licensor: wapsol (labs) gmbh |
| `ludo-desktop` | BSL 1.1 → Apache-2.0 · Licensor: wapsol (labs) gmbh |

BSL ≠ open source: source is visible + modifiable for **non-production** use; production use
needs a commercial license until the change date, when it converts to Apache-2.0.

## Cluster topology — broker-mediated, never direct calls

```
  clients (web · portal · superadmin · desktop · omg CLI · mobile…)
        │ HTTPS (commands 202 · resumable SSE)
        ▼
  ludo-gateway  ── PUBLIC edge, stateless ×N ──  auth · tenancy · vault ·
        │                                         migrations state machine · commerce
        │ enqueue job            ▲ subscribe + project event stream
        ▼                        │
     BROKER  (NATS JetStream — decision euroblaze/ludo #443)
        │ consume + ack          │ publish lifecycle events (Contract B)
        ▼                        │
  ludo-agent  (worker + engine + 3 stores) — INTERNAL ONLY, no public port, no PII
```

- The **gateway** is the only thing that talks to the broker; clients never touch
  NATS, and never reach the agent. It stores `account_id` authority + customer state.
- The **agent** is a single-tenant worker reachable only via the broker / internal
  network. Jobs name the customer by the opaque **`account_id`** + anonymized
  fingerprint only — **no customer PII** crosses into agent stores. Its own HTTP
  surface is read-only introspection + health.
- Job submission and event delivery go through the **broker, not HTTP**.
- **In transition (`flywheel#96`, phases B1–B5):** `ludo-apps` still runs the full
  backend today and talks to a **stub** (`ludo-apps/backend/libs/integrations/ludo_agent_client.py`).
  The gateway absorbs that backend (auth, vault, migration state machine, broker
  client, SSE relay → durable JetStream projector) and the frontends repoint to it.
  Until cutover, treat duplicated control-plane code as *intentional, gated* — not a
  conflict to resolve ad hoc.

## Shared vocabulary (use these exact terms across all repos + docs)

- **Execution model** (locked, `euroblaze/ludo` #430-A — use **Type**, never "Kind"):
  **Migration** (control-plane-owned, customer-facing; the broker message; mode
  `estimate` | `migrate` | `dry-run`) → **Session** (the agent's single run of a
  Migration, **1:1**; the Ephemeral `Session` `s_…`; stored as `ludo_session_id`) →
  **Job** (a discrete, independently-queued/retryable async **step**; a Session
  decomposes into **N Jobs**; each has a **JobType** — `extract` · `load` · `discover`
  · `verify` · `diagnose` · `reconcile` · `rollback` — and a scope) → **Model** (the
  Odoo model a Job acts on) → **Batch** (records per `load` RPC). **Turn** (one Cortex
  round-trip + tool dispatch) is **orthogonal** — the Cortex wakes only for reasoning
  Jobs. **No "Task"** (collides with queue-library vocab). Cardinality: 1 Migration → 1
  Session → N Jobs; Job → 1 Model; load → M Batches; Session → N Turns.
- **Identity** (locked, #430-B): **`account_id`** is the one opaque, **persisted**
  per-customer id (authority = the control plane). It keys the xmlid component
  (`ludo.{account_id}-…`), MinIO prefix, `sessions.customer_id` *value*, and wiki page
  names. The Migration/Job payload carries it; **no PII** else crosses into agent
  stores. **`slug`** is an operator/dev CLI handle to resolve `account_id` + creds
  (`CustomerProvider.resolve(slug)`) — **never persisted**, absent in production.
  Retired: **`customer_ref`**; **`customer_id`** is the legacy column/param name
  holding `account_id`, converging by rename-on-touch.
- **Events** (locked, #430-D — the agent→control-plane progress stream, **Contract
  B**): fire-and-forget, one-way (agent publishes, the consumer subscribes, no ack).
  Envelope (6 fields): `session_id` · **`type`** · `payload` · `at` · `schema_version`
  · **`checkpoint_required`**. Event **types**: `session_started`/`session_end` ·
  `model_started`/`model_completed` · `job_started`/`job_completed`/`job_failed` ·
  `turn_started`/`turn_completed` · `safety_event` · `checkpoint_requested` (reserved).
  `kind`→`type` + the new enum is **Contract B v2** (`schema_version "2.0"`), a
  coordinated cross-repo change (#414/#415/flywheel #79). **`checkpoint`** = an
  operator review/decision milestone (the former "gate"); the resumable session-state
  snapshot is a different thing — call it a **state checkpoint** if both appear.
- **Cortex** = the LLM (`ludo-agent/src/ludo/llm/` — router + anthropic/openai/groq).
  Woken **only on surprise**; the deterministic body does the rest.
- **Data vs Knowledge — never cross.** *Data* = records being migrated + bulk
  artifacts → MinIO + the target Odoo. *Knowledge* = what the system learnt →
  git-backed `knowledge/` wiki + the core prompt (+ Agent Skills where warranted).
- **Three memory classifications** (canonical term first, alias = wiki dir name).
  Full physical layout is the single source of truth in `ludo-agent/arch.md` § 7.3:
  **Transient** (aka *ephemeral*) — one run: SQLite Session/turns + MinIO checkpoints;
  staging in `knowledge/ephemeral/`) · **Episodic** — two types: *per-customer*
  (system of record = the **control-plane DB**, `flywheel#92`; agent working copy at
  `knowledge/episodic/customers/`) and *per-version-pair*
  (`knowledge/episodic/pairs/<pair>/{renames,reconciled}/`) · **Learnings** (aka
  *longterm*) — general, cross-customer (`knowledge/longterm/` = types catalogue,
  Odoo facts, recipes). All wiki subpaths resolve through `ludo.knowledge.paths`.
- **Knowledge content + verbs** (locked, #430-C/E): **finding** (Transient, raw note)
  · **recipe** (Episodic, per-pair values) · **diagnosis** (Episodic, reconciled root
  cause) · **page** (Episodic, customer page) · **type** (Learnings, cross-pair
  catalogue entry; `RootCauseType` at `knowledge/longterm/types/`. `RootCauseType`
  (diagnosis taxonomy) is distinct from `JobType` (queue step) — qualified names
  disambiguate). Verbs: **reconcile** (finding → wiki rule) · **promote**
  (cross-customer evidence flips `promoted`).

## Agentic surface — Tools, Skills, MCP

Only **`ludo-agent`** is agentic; everything else is a deterministic client or
transport. The three concepts (Anthropic guidance:
[tools](https://www.anthropic.com/engineering/writing-tools-for-agents),
[skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)):

- **Tool** = a contract between a deterministic system and the agent — one callable
  primitive (*the hammer*). LUDO's live set: `ludo-agent/src/ludo/tools/`
  (`register_builtin_tools`, `omg tools list`). Design rule: consolidate, namespace,
  token-efficient returns, actionable errors.
- **Skill** = a directory (`SKILL.md` + resources) of **procedural know-how** —
  *how to compose tools toward a goal* (*the carpentry skill*). Use the **Agent
  Skills open standard** with progressive disclosure, only where real recurring
  know-how exists.
- **MCP** = the **transport** that publishes tools/skills across components — the
  "Tools-catalog other components can borrow from." Target home: a namespaced MCP
  surface published via **`ludo-gateway`** (kernel-phase, post-autonomy).

**Competence model** (the agent, redesign `euroblaze/ludo` #468): two layers —
**Core** (deterministic body + the Cortex loop) over a **knowledge substrate of
verified conclusions** (reactive cache + wiki + control-plane episodic SoR). The old
three-layer "Core + Skills + Wiki" ladder (`findings→wiki→skill→core`) is being
retired; skills are **not** a graduation target but an open-standard packaging of
know-how. Detail: `ludo-agent/docs/proposals/tools-skills-mcp.md` +
`harness-brain.md`.

## Where to look (defer to repo CLAUDE.md for specifics)

- **Agent internals, tools, Cortex, stores, autonomy bar** → `ludo-agent/CLAUDE.md`
  (long) + `ludo-agent/arch.md` (topology/contracts).
- **Edge API, auth/tenancy/vault, Contract A, commerce, broker seam** →
  `ludo-gateway/` README + CLAUDE.md (the control-plane successor).
- **Frontends, locale, Vue/Vite build** → `ludo-webapps/.claude/CLAUDE.md`.
- **CLI client** → `ludo-cli/` README. **Desktop client** → `ludo-desktop/` README +
  `prd_macos.md`.
- **Cross-repo contracts (the seams)** → **canonical in `ludo-init/contracts/`** (A/B/C +
  shared types); consumers vendor from there (`scripts/check_contract_drift.py`). Detailed
  cross-repo topology → `ludo-init/docs/cluster-architecture.md`; thin-client Contract A guide
  → `ludo-init/docs/contracts-consumer-guide.md`; cluster proposals → `ludo-init/docs/proposals/`.

## Commands (basics — repo files have the full set)

```
# ludo-agent (cd ludo-agent; uv + Python 3.12)
make check                                      # lint + typecheck + test (before push)
omg migrate-customer --customer <slug> --source-version V15 --target-version V18
# ludo-apps (cd ludo-apps) — frontends + (retiring) backend
APP_ENV=dev uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
npm run dev            # 3 Vue 3 + Vite dev servers
# ludo-gateway / ludo-omg — see each repo README
```
Apps skills `run-ludo-flywheel` / `deploy-ludo-flywheel` drive running/deploying that
stack — prefer them over ad-hoc commands.

## Drift to be aware of

- **Topology:** the gateway (`flywheel#96`) is the new public edge and is **absorbing
  the apps backend**; any doc still calling `ludo-apps` "the only BFF/control-plane"
  (incl. `ludo-apps/.claude/CLAUDE.md` today) is pre-gateway and stale — gateway is
  authoritative for the control plane post-cutover.
- **Skills:** the agent's *bespoke* skills layer (manifest/trigger/graduation ladder)
  had zero organic graduations and is being retired (#470); skills re-found on the
  open standard. If a doc still describes `findings→wiki→skill→core` as live, it
  predates the #468 redesign.
- **Frontends are Vue 3 + Vite** (public/portal/superadmin); the old
  React-UMD/Babel stack (`sync_theme.py`/`build_jsx.js`/JSX) was removed — do not
  reintroduce it.
- **Single-replica today:** the apps backend is single-replica (SQLite file-lock) +
  in-memory SSE relay; scale lands with the gateway + broker (flywheel #86).
