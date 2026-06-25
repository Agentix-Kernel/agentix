# PRD — LUDO: Website, Portal & Build Orchestration

*A Simplify-ERP™ NanoService · Odoo migration platform*
Status: Draft v0.5 (unified) · Owner: Simplify-ERP · Audience: DACH B2B Odoo

> **Canonical home:** this is the single source of truth for the unified PRD (the former
> `ludo-webapps` copy is now a pointer here). **Known reconciliation debt** (tracked, not yet
> swept): *"LIBRADO"* = the retired name for **`ludo-agent`** (repo `euroblaze/ludo`); directory
> names have changed — *`ludo-apps`→`ludo-webapps`*, *`ludo-omg`→`ludo-cli`*. The current cluster
> truth lives in [`CLAUDE.md`](CLAUDE.md) (vocabulary + topology), [`docs/cluster-architecture.md`](docs/cluster-architecture.md),
> and [`contracts/`](contracts/) (the canonical seams) — defer to those where this PRD's naming lags.

This document merges the product/UX spec (former Website-PRD v0.1) with the system architecture + Claude Code build orchestration (former Section 13 v0.4), integrating findings from the LIBRADO source review (euroblaze/ludo).

Three parts:
- **Part A — Product** (§1–9): what LUDO does, for whom, what each screen is.
- **Part B — Architecture** (§10–13): topology, job lifecycle, contracts, tech stack.
- **Part C — Build & Orchestration** (§14–17): Claude Code agents, git, gates.

> **⚠️ 0.2 convergence — transport changed.** Where this PRD says *"apps/api calls
> ludo-agent `POST /sessions` directly"*, read that as the **current stub** (the HTTP
> client `backend/libs/integrations/ludo_agent_client.py`). The agreed **0.2 target is
> broker-mediated**: apps/api **enqueues** jobs onto a broker (**Redis Streams via
> SAQ** — recommended, pending final confirm) and the agent runs them as an **internal
> worker** that publishes lifecycle events back over the broker; apps/api relays SSE to
> the browser. The split is unchanged in spirit — **apps is the only BFF/control-plane;
> the agent is an internal worker that stores no customer PII (opaque `customer_ref` +
> per-job creds)** — only the *direct-HTTP* wording is stale. See the cross-repo big
> picture in the workspace-root `CLAUDE.md` and
> [`async-harness-architecture.md`](https://github.com/euroblaze/ludo/blob/main/docs/async-harness-architecture.md).
> Tracked: [#78](https://github.com/euroblaze/ludo-flywheel/issues/78)–[#88](https://github.com/euroblaze/ludo-flywheel/issues/88)
> (apps) · [euroblaze/ludo #413–419](https://github.com/euroblaze/ludo/issues/413) (agent).

---

# PART A — PRODUCT

## 1. Purpose

- Public site sells LUDO. Portal delivers it. LIBRADO (the agent) executes it.
- One funnel: **anonymous estimate → claimed account → paid migration → subscription**.
- Estimate is the lead magnet. No email required to see a number.
- Two account types: **Customer** (own migrations) and **Superdev** (many customers' migrations).
- Backend: Simplify-ERP staff (**Superadmin**) oversee all, gate every job before execution.

## 2. Goals / success metrics

- Primary: **signups**. Maximize % of visitors who claim an estimate.
- Secondary: virality — colleague invites sent, referral signups.
- Tertiary: subscription conversions (1€/day plan).
- Protect deliverability + UWG compliance (double opt-in newsletter).
- Funnel KPIs: estimate-run rate, anon→claimed, claimed→paid, invites/account, newsletter opt-in rate.

## 3. Users / personas

- **Anonymous visitor** — runs calculator, sees price, no login.
- **Customer** — one Odoo estate. Adds keys, runs scans, pays, tracks migration.
- **Superdev** — agency/freelancer. Manages many customers, their keys, scans, migrations, billing.
- **Technician (Simplify-ERP)** — accompanies migrations, responds to support. No UI in v1 (email-only).
- **Superadmin (Simplify-ERP)** — single owner. Full control: pricing config, approval gate, queue, Vault audit, NOVEL handling.

## 4. Auth

- **GitHub OAuth only** for portal (customer + superdev). LinkedIn deferred — added later as its own atomic PR if needed. No password DB.
- One-click sign-in from any capture point.
- Role assigned post-login: Customer (default) / Superdev (requested or granted).
- Superdev = elevated Customer with multi-tenant scope.
- **Superadmin = single owner, no OAuth.** Key-only: `SUPERADMIN_KEY` from `apps/superadmin/.env` → key entry form → short-lived signed token (httpOnly cookie). Superadmin auth is fully self-contained, independent of the portal OAuth system.
- Session persists; "claim my estimate" flow pre-fills from the anonymous estimate.

---

## 5. Public site (`web` — ludo.simplify-erp.de)

Vue/Vite. No auth. Top navigation.

### 5.1 Menu (public)

- **LUDO** — service overview (hero, ~1 week, 0 downtime, 7 components).
- **How it works** — 4 steps (Connect · Approve · Migrate+test · Deploy).
- **Tracks** — Community / Enterprise + cross-combinations.
- **Price** — calculator + subscription (1€/day) + what's included.
- **FAQ**
- **About** — Simplify-ERP, NanoServices, sovereign-private-cloud.
- **DE / EN** toggle.
- **Sign in** (GitHub).
- Persistent primary CTA: **"Free upgrade scan →"** (sticky on mobile). Links to portal.

### 5.2 Price menu — calculator

- Model after simplify-erp.de/en/odoo-upgrade, extended for cross-combos.
- Inputs: source license (Community/Enterprise) · target license (Community/Enterprise → 4 combos, §7) · source version (v11–v18) · target version (v11–v19) · custom modules (None / 1–5 / 6–15 / 16+) · database size (Small/Medium/Large) · code quality (Good/Mixed/Legacy, disabled if no custom modules).
- Outputs (live, no email): total cost + range · timeline (~5 days) · automation % (~95%) · line breakdown (DB+field mapping / filestore+config / custom modules / validation+test) · complexity badge.
- Below result: **"Save this estimate"** → GitHub sign-in capture. ← primary conversion event.
- Cross-sell strip: **1€/day subscription** card.
- Anonymous calculator = rough guess. Key-verified scan (§6.3) replaces it with a real estimate.

### 5.3 Capture & onboarding (critical path)

- Goal: lowest possible friction to a captured lead.
- Entry tiers (progressive disclosure):
  1. **Instant estimate** — version pickers only, zero auth, zero email. Result in seconds.
  2. **Claim estimate** — to save / get full report / book → one-click GitHub. ← primary conversion event.
  3. **Connect key** — add Odoo API key in Vault → real SCOTCH scan replaces the guess.
  4. **Approve & pay** → migration job submitted (held for superadmin approval).
- Capture points everywhere: hero CTA, after calculator result, footer, FAQ, exit-intent (light).
- Post-signup onboarding checklist (dashboard): Connect key → Run scan → Review estimate → Invite colleague → Approve.
- Anonymous estimate stored client-side + server token; auto-attached to account on claim.

### 5.4 Virality / email-a-colleague

- **We provide the mail sender** (server-side send, branded, UWG-safe).
- "Share this estimate with a colleague" → prefilled subject/body, recipient email, optional note. Forward includes estimate summary + reopen link + soft CTA.
- "Invite teammate to this migration" (collaborator on same account).
- Referral attribution: track who shared, who signed up. Surface in superadmin analytics.
- Share targets: email (primary), copy link, LinkedIn (share intent, not auth).
- Guardrail: rate-limit sends, no scraped lists, recipient entered manually (UWG).

### 5.5 Newsletter (Mautic)

- Subscribe + **unsubscribe** both supported (one-click unsub link in every mail).
- Double opt-in (UWG / DACH requirement).
- ESP: **Mautic** ("mauxy"), GitHub-hosted infra.
- Sources: footer field, onboarding checklist, account settings toggle.
- Preference center in superadmin (frequency, topics).

### 5.6 Subscription promo — 1€/day

- Promoted across site (hero strip, Price page card, dashboard).
- Position: continuous-currency plan — stay on latest Odoo, ongoing scans + priority migration slots. *(scope = open question §18)*
- Billing: daily rate displayed, charged monthly (~€30/mo) — confirm. Provider: **Mollie**.
- CTA: "Stay current for 1€/day".

### 5.7 Footer

- **Col 1 — Product**: LUDO · Tracks · Price · SCOTCH portal · FAQ
- **Col 2 — Company**: About Simplify-ERP · NanoServices · Contact · Impressum
- **Col 3 — Legal**: Datenschutz/Privacy · Terms (AGB) · Cookie settings
- **Col 4 — Stay updated**: Newsletter subscribe (Mautic, double opt-in) + unsubscribe link
- Bottom bar: endorsed-brand line ("LUDO is a NanoService by Simplify-ERP™") · address + DE legal entity · GitHub · LinkedIn · DE/EN toggle · © year

---

## 6. Customer portal (`portal` — portal.ludo)

Vue/Vite SPA. GitHub OAuth. Left sidebar. Role-gated (Customer / Superdev share the shell; items conditional on session role claim).

### 6.1 Menu (Customer)

- **Dashboard** — onboarding checklist, active migrations, latest estimate, next action.
- **Vault** — manage Odoo API keys (encrypted).
- **Estimates / Scans** — list + estimation status + computed cost.
- **Upgrade Jobs** — list + migration status + per-job cost (live when running).
- **Billing** — subscription (1€/day), invoices, payment method (Mollie).
- **Support** — ticket system (thread per job): submit, view, reply. Chat deferred.
- **Invite** — share estimate / invite colleague (virality).
- **Settings** — profile, newsletter prefs, language, sign out.

### 6.2 Vault

- Store Odoo API keys + connection (URL, db, source/target versions).
- Encrypted at rest (HashiCorp Vault), never shown plaintext after save (mask + last-4).
- One key → many scans/migrations. Add / rotate / revoke. Access-logged.
- The app DB stores **references only**, never raw keys.

### 6.3 Estimation status

- States: Draft → Initial scan → Thorough scan (optional) → Estimate ready.
- Each shows computed cost + breakdown + complexity.
- Anonymous estimate (calculator guess) vs key-verified estimate (SCOTCH scan + LIBRADO estimate module) distinguished.

### 6.4 Migration (Upgrade Job) status

Customer sees a friendly progress view; the backend runs the LIBRADO job state machine (§11). SSE milestone events drive the live display.

**Customer-facing display ← backend state:**

| Customer sees | Backend state | Notes |
|---|---|---|
| Awaiting approval | `pending_approval` | Job submitted, Simplify-ERP must approve |
| Approved / queued | `approved` | Approved, session starting |
| Migrating | `running` | Live per-model progress via SSE (model_started / model_completed) |
| Validating | `running` (final stage) | Post-migration validation, gap report generated |
| Delivered | `migrated` / `partial_migrated` | Package link + credentials by email; gap report attached |
| Under review | `novel` | Agent hit a knowledge gap; Simplify-ERP intervenes (customer not alarmed) |
| Paused / retrying | `aborted` → resume | Infra/budget failure; resumed from checkpoint |

- Per job: track (Community/Enterprise + combo), versions, assigned technician, computed + actual cost, deliverable package link, support thread.
- Status timeline + notifications (in-app SSE + email via Mautic/transactional).
- **Deployment** is customer-side (download package, deploy to own SPC). Self-serve deployment automation is out of scope v1 (§19).

### 6.5 Payments

- One-off migration fee (per approved estimate) + 1€/day subscription.
- Invoices downloadable. VAT handled (DE/EU B2B, reverse charge).
- **Provider: Mollie.** `MOLLIE_API_KEY` in `apps/api/.env`. Payment confirmation via Mollie webhook (POST callback); validate by GET to Mollie API to verify status (no signature by default).

### 6.6 Support (tickets)

- Ticket system, thread per job. Rapid-response SLA messaging.
- Attach gap reports, screenshots. Chat widget deferred to a later phase.

---

## 7. Service — tracks & cross-combinations

- **Community Track** — all versions.
- **Enterprise Track** — incl. deprecated (>3 versions past window).
- **Cross-combinations** (calculator + tracks page):
  - Community → Community (version upgrade)
  - Enterprise → Enterprise (version upgrade)
  - **Community → Enterprise** (license migration)
  - **Enterprise → Community** (license migration)
- Each combo has its own copy/objections (matches email mini-campaign segmentation).
- 7 components always covered (DB · type check · field map · filestore · custom modules · config · validation) via the Odoo DataLake. Executed by LIBRADO model-by-model (the 7 components are the customer-facing framing; the agent works at Odoo-model granularity).

---

## 8. Superdev (multi-customer)

Same portal shell, additional items conditional on superdev role.

### 8.1 Additional menu

- **Upgrade Jobs** — all customers, filterable by customer / status / version.
- **Customers** — list, add, switch context (persistent context switcher in nav).
- **All estimates** — aggregate pipeline.
- **Scan Debugger** — raw scan output, API key tester.
- **Vault (per customer)** — keys scoped per customer, isolated.
- **Billing** — per-customer + roll-up; who pays (superdev vs end-customer) configurable.
- **Team** — invite collaborators.

### 8.2 Behavior

- Tenant isolation: each customer's keys/data siloed; superdev sees own roster only.
- Bulk: run scans, compare estimates, queue jobs across customers.
- Status dashboards aggregate (X migrating, Y awaiting approval, etc.).

---

## 9. Superadmin console (`superadmin` — superadmin.ludo)

Vue/Vite SPA. **Single owner, key-only auth (§4).** Left sidebar. Internal ops only — not linked from public site or portal. Merges the operational queue/approval surface with business analytics.

| Item | Notes |
|---|---|
| Dashboard | KPIs: queue depth · active jobs · completion rate · error rate · total LLM cost (period) · funnel (estimate→claim→pay) · referral conversions |
| Pending Approval | Approval gate — review job detail + cost estimate, approve or reject. Technicians notified by email. |
| Active Jobs | Live SSE event stream per job · cost accumulating · per-model progress |
| NOVEL Queue | Jobs that hit a knowledge gap. Distinct from failures. Action: "Add Catalogue Entry" → submit new job. |
| All Jobs | Full history — search, filter, export. Terminal state + total cost. |
| Accounts | All customers + superdevs. |
| Pricing config | Edit calculator rates, combos, ranges without deploy. |
| Newsletter / Mautic | Lists, segments, opt-in audit, preference center. |
| Vault audit | Access logs (no plaintext key exposure). |
| System | ludo-agent /healthz · MinIO status · Vault status · safety-event counts per session |
| Settings | |
| Logout | |

**Job state display:**
- `pending_approval` → Pending Approval queue, Approve / Reject actions
- `approved` → transitional, shown briefly before session confirmed
- `running` → live event stream, cost accumulating
- `novel` → NOVEL Queue, "Add Catalogue Entry → Submit New Job" (not resume)
- `aborted` → "Resume" action (PATCH /jobs/{id}/resume)
- `migrated` / `partial_migrated` → archived, cost visible

---

# PART B — SYSTEM ARCHITECTURE

## 10. Topology & runtime

**Two repos. Two runtime environments.**

| Repo | Language | Contents | Deployed at |
|---|---|---|---|
| `ludo-app` | Vue/Vite (frontends) + TBD (api) | `apps/api` · `apps/portal` · `apps/superadmin` · `apps/web` | portal.ludo · superadmin.ludo · ludo.simplify-erp.de |
| `ludo-agent` (LIBRADO) | Python 3.12 | Migration engine · FastAPI · Typer CLI | Internal — called by `apps/api` |

**ludo-agent runtime: 2 containers** — `librado` (Python: FastAPI + CLI) + `minio` (S3-compatible blob store). ludo-agent also owns its own SQLite+FTS5 for ops state, **separate** from `apps/api`'s SQLite. Never shared.

**Runtime diagram:**

```
Customer (portal / web)
        │ HTTPS
        ▼
  apps/api ─── apps/api SQLite (jobs, users, Vault key refs, billing)
        │                │
        │          Vault (Odoo credentials)
        │
        │  POST /sessions  (after superadmin approval)
        ▼
  ludo-agent FastAPI ─── ludo-agent SQLite (sessions, turns, costs, audit)
        │                        │
        │                   MinIO (blobs, checkpoints)
        │
  engine runs async (per-model sessions, middleware chain)
        │
  SSE /sessions/{id}/events  (ludo-agent publishes)
        │
  apps/api SSE proxy  (apps/api subscribes internally, re-publishes)
        │
  portal · superadmin  (subscribe to apps/api SSE, real-time status)
```

**Principles:** no long synchronous cascades (`apps/api` returns 202 immediately) · frontends talk only to `apps/api`, never to ludo-agent directly · `apps/api` is the single integration seam (job storage, approval gate, SSE relay, billing).

> **0.2 target topology.** The diagram above shows the **current stub** (direct
> `POST /sessions` HTTP). The agreed target inserts a **broker** at the `POST /sessions`
> seam: `apps/api ──enqueue──▶ BROKER (Redis Streams/SAQ) ──consume──▶ ludo-agent
> worker`, with lifecycle events published back over the broker and relayed as SSE.
> apps/api stays the single integration seam; the agent becomes an **internal worker
> with no public port**, named the customer by an **opaque `customer_ref`** (no PII),
> with Odoo creds passed **per-job** from the Vault ([#80](https://github.com/euroblaze/ludo-flywheel/issues/80)).
> The "2 containers" note for ludo-agent gains a **broker** alongside (internal-only,
> [#88](https://github.com/euroblaze/ludo-flywheel/issues/88)).

**LIBRADO key facts** (from code review): FastAPI HTTP + Typer CLI share one core · storage = MinIO (blobs/checkpoints) + SQLite+FTS5 (ops) + git memory (domain knowledge) · LLM = Claude primary (OAuth via `~/.claude/.credentials.json`), OpenAI/Groq fallback · architecture is zero per-action confirmations (safety via dry-run + SafetyGate middleware) · two-level orchestration: outer customer-orchestrator agent → inner per-model sessions.

## 11. Job lifecycle & state machine

### States

```
pending_approval → approved → running → migrated
                                      → partial_migrated
                                      → novel
                                      → aborted ──→ running  (via resume)
```

- `novel` — agent completed but hit an unresolvable error pattern (no catalogue match). Not a failure. Triggers operator action: add catalogue entry, then **new job submission** (not resume — resuming would hit NOVEL again, it's a knowledge limit not an infra limit).
- `partial_migrated` — orchestrator ran multiple plan cycles; some models converged, some didn't; declared acceptable.
- `aborted` — infra/budget failure. Checkpoint-first: **resumable** from last MinIO checkpoint without re-running prior work.

### Session hierarchy

- **Customer session** (orchestrator): one `session_id`, owns plan cycles, decides model order + per-model budgets, emits `multi_model_started`.
- **Model sessions** (N inner): one per model, own `session_id`, emit turn-level events.
- Portal + superadmin subscribe to the **customer session** stream. Model-level streams available for ops drill-down.

### Full async flow

```
1. SUBMIT — Customer → portal/web → POST /jobs → apps/api stores (pending_approval), returns 202 + job_id.
2. APPROVAL — Superadmin → PATCH /jobs/{id}/approve → apps/api calls ludo-agent POST /sessions (to build)
   → 202 + customer_session_id → api stores it, status=running → api begins internal SSE subscription.
3. PROCESSING (fully automated, zero human gates v1) — orchestrator proposes plan → per-model sessions run.
   Each milestone fires a SessionEvent (fire-and-forget, no ack). apps/api validates against Contract B,
   updates job SQLite, re-publishes translated event on its own SSE.
4. PUSH — portal shows live progress (human-readable stages); superadmin shows all active jobs + cost.
5. COMPLETION — session_end → terminal state.
   migrated/partial → transactional email + package/credentials.
   novel → NOVEL Queue; ops adds catalogue entry → submits new job.
   aborted → Resume action available.
6. RESUME (aborted only) — PATCH /jobs/{id}/resume → ludo-agent POST /sessions/{id}/resume (to build)
   → loads MinIO checkpoint, continues from last completed model → api re-subscribes, status=running.
```

## 12. Contracts

### Contract A — `ludo-app/packages/contract-internal/openapi.yaml`
OpenAPI (REST). Covers every `apps/api` endpoint: job lifecycle (submit, approve, status, resume), auth, estimates, billing, SSE relay subscription. Consumers: `portal`, `superadmin`, `web` generate typed clients. No hand-written API types in any frontend. Change rule: REST surface change → Contract A PR first → frontends regenerate. One tier, no further cascade.

### Contract B — [`contracts/session-event.schema.json`](contracts/session-event.schema.json)
JSON Schema for the agent→gateway event envelope. Covers the SSE event structure. **Canonical contracts** (A/B/C + shared types) now live in [`contracts/`](contracts/) here in `ludo-init` — see [`contracts/README.md`](contracts/README.md) for authorship + the vendor model; don't restate the field list. (Consumers vendor byte-identical copies, guarded by `scripts/check_contract_drift.py`.)

> **Known gap.** The agent does **not** yet emit `schema_version` / `gate_required`, so
> the relay silently drops non-conforming events — [euroblaze/ludo #414](https://github.com/euroblaze/ludo/issues/414)
> (agent emits the envelope) + [#79](https://github.com/euroblaze/ludo-flywheel/issues/79)
> (apps maps agent-native events → Contract B in `sse_relay`).

```json
{
  "session_id": "string",
  "kind": "turn_started | turn_completed | safety_event | session_end | multi_model_started | model_started | model_completed",
  "payload": "object (kind-specific keys)",
  "at": "ISO-8601 datetime",
  "schema_version": "string (e.g. '1.0')",
  "gate_required": "boolean (default: false)"
}
```

| kind | payload keys | status |
|---|---|---|
| `multi_model_started` | `customer_id`, `models[]`, `per_model_budget_usd` | existing |
| `model_started` | `model`, `position`, `total_models`, `budget_usd` | **to build** |
| `turn_started` | `turn_index`, `model` | existing |
| `turn_completed` | `turn_index`, `model`, `cost_usd`, `tokens_in`, `tokens_out` | existing |
| `safety_event` | `kind` (sub-kind), `tool_name`, `detail` | existing |
| `model_completed` | `model`, `outcome`, `cost_usd`, `turn_count` | **to build** |
| `session_end` | `outcome`, `total_cost_usd`, `total_turns`, `abort_reason?` | existing |

Consumers: `apps/api` only (internal SSE subscription → validate → write to job table → re-publish). Frontends never see raw Contract B events. Change rule: Contract B change → ludo-agent impl PR → apps/api SSE handler update only. No frontend cascade. Permissive validation both sides (`additionalProperties: true`). `gate_required: false` default — enables future decision gates without schema break.

## 13. Tech / data stack

- **Frontends** (`portal`, `superadmin`, `web`): Vue/Vite. Build `vite build` · dev `vite dev` · test `vitest run`.
- **`apps/api`**: language/framework TBD (open question §18). SQLite (name in `.env`; dev has own DB; never shared dev/prod). Numbered migration files.
- **`ludo-agent` (LIBRADO)**: Python 3.12. MinIO + SQLite+FTS5 + git memory. Claude/OpenAI/Groq.
- **Secrets**: Vault for Odoo API keys + tokens (encrypted at rest; app DB stores references). `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`, `MOLLIE_API_KEY` in `.env`. `SUPERADMIN_KEY` in `apps/superadmin/.env`. Claude OAuth at `~/.claude/.credentials.json`.
- **Auth**: GitHub OAuth (portal); key-only (superadmin).
- **ESP**: Mautic ("mauxy") — newsletter + colleague-share. Double opt-in.
- **Transactional mail**: status notifications, estimate-share, invoices.
- **Payments**: Mollie.
- **Scan engine**: SCOTCH portal API (connect key → scan → estimate). Feeds LIBRADO estimate module.
- **i18n**: DE + EN.
- **Roles**: anon / customer / superdev / superadmin. Technician = email-only, no UI v1.
- **Admin surfaces: 2** — (1) Customer/Superdev portal (one codebase, role-gated). (2) Superadmin console. Plus the public site + api backend. Technician UI deferred to v2.

---

# PART C — BUILD & ORCHESTRATION (Claude Code)

Drives parallel development + parallel testing across all apps, coordinates git across both repos, guarantees integrity.

## 14. Orchestration model & agent roster

- **One orchestrator Claude Code session** + **subagents** (`.claude/agents/<name>.md`, own context/tools/prompt, run in parallel within a tier) + **git worktrees** for isolation.
- Subagents over agent teams: teams span separate sessions with peer coordination, ~7× token cost in plan-heavy flows. Subagents suffice at this scale.
- Tier-based fan-out: contracts land first → implementations parallel by tier → tests per-app parallel → e2e last. No blocking on downstream consumers.

### Dev agents

| Agent | Repo | Scope | Tools |
|---|---|---|---|
| `contract-b-keeper` | `ludo-agent` | `contract/session-event.schema.json` | Read, Edit, Bash |
| `dev-agent` | `ludo-agent` | `src/librado/` — engine, tools, middleware, **POST /sessions** + **POST /sessions/{id}/resume** (to build) | Read, Edit, Bash, Grep, Glob |
| `dev-api` | `ludo-app` | `apps/api` — job CRUD, approval gate, ludo-agent HTTP client, SSE relay | Read, Edit, Bash, Grep, Glob |
| `contract-a-keeper` | `ludo-app` | `packages/contract-internal/openapi.yaml` | Read, Edit, Bash |
| `dev-portal` | `ludo-app` | `apps/portal` | Read, Edit, Bash, Grep, Glob |
| `dev-superadmin` | `ludo-app` | `apps/superadmin` | Read, Edit, Bash, Grep, Glob |
| `dev-web` | `ludo-app` | `apps/web` | Read, Edit, Bash, Grep, Glob |

### Test agents

| Agent | Scope |
|---|---|
| `test-agent` | ludo-agent unit · Contract B self-conformance · POST /sessions smoke |
| `test-api` | api unit · Contract A conformance · Contract B SSE handler validation · relay correctness |
| `test-portal` / `test-superadmin` / `test-web` | unit · Contract A client conformance (web also: calculator logic) |
| `test-e2e` | full lifecycle: submit → approve → SSE events → terminal state (incl. NOVEL + resume) |

All test agents: `tools: Read, Bash, Grep`. Model: sonnet.

### Integrator
Git only. Merges `ludo-agent` first, then `ludo-app`. Reads GitHub token from `~/.claude/.credentials.json`.

**Dev↔Test loop:** `dev-X` finishes → spawn `test-X` → fail = verbatim failure list in prompt → re-spawn `dev-X`. Loop to green. Then `test-e2e`. Then `integrator`.

### Which agents spawn

| Change type | Agents |
|---|---|
| Full cross-app feature | `dev-api` + `dev-portal` + `dev-superadmin` + `dev-web` (parallel) |
| API + one frontend | `dev-api` + the one frontend |
| Single app tweak | one `dev-X` |
| ludo-agent + api integration | `dev-agent` + `dev-api` (parallel, after Contract B lands) |

## 15. Git worktrees & change cycle

Worktrees (one per agent, no collisions):
```bash
# ludo-app
git worktree add ../wt-api feat/api/<slug>          # + portal, superadmin, web
# ludo-agent
git worktree add ../wt-agent feat/agent/<slug>
```
Conventional Commits `type(scope): subject`. Each agent commits its worktree only; no agent pushes to `main`; integrator owns merges.

**Change cycle (orchestrator runbook):** classify first, fan out only what's affected.
- **Tier 0 — Contracts:** Contract B → `contract-b-keeper` (no frontend cascade); Contract A → `contract-a-keeper` (no agent cascade); both → B then A.
- **Tier 1 — Implementations (parallel after their contract lands):** B → `dev-agent` + `dev-api`; A → `dev-portal` + `dev-superadmin` + `dev-web`.
- **Tier 2 — Per-app tests (parallel):** each `dev-X` → matching `test-X`; fail → re-spawn with verbatim failures.
- **Tier 3 — E2E:** `test-e2e` (happy, NOVEL, resume).
- **Tier 4 — Integration:** `integrator` merges ludo-agent first, then ludo-app → `integration` → `main`.
- **Cleanup:** remove worktrees, delete feature branches.

## 16. CLAUDE.md & agent definitions

### `ludo-app/CLAUDE.md`
```md
## Contracts
- packages/contract-internal/openapi.yaml = Contract A. Source of truth: api ↔ frontends.
- ludo-agent SSE events conform to Contract B (ludo-agent/contract/session-event.schema.json).
- apps/api is the only Contract B consumer. Frontends never see raw agent events.
- api REST change → Contract A PR first. Event schema change → Contract B PR in ludo-agent first.

## ludo-agent integration (apps/api)
> **0.2:** "POST /sessions" / "subscribe to SSE" below describe the **current stub**;
> the target replaces both with **broker enqueue + broker event subscription** (Redis
> Streams/SAQ) — see the banner at the top of this PRD and
> [#78](https://github.com/euroblaze/ludo-flywheel/issues/78)/[#79](https://github.com/euroblaze/ludo-flywheel/issues/79).
- Job submission: POST /sessions to ludo-agent after superadmin approval. *(0.2: enqueue on the broker instead.)*
- Event relay: subscribe to ludo-agent /sessions/{id}/events SSE internally; translate → update job SQLite
  → re-publish on apps/api SSE channel. *(0.2: subscribe to the broker event stream instead.)*
- Session hierarchy: store customer_session_id on job. Model sessions = children (read-only drill-down).
- Resume: PATCH /jobs/{id}/resume → ludo-agent POST /sessions/{id}/resume.
- Never call ludo-agent synchronously in a request path. All calls return 202.

## Job states
- pending_approval | approved | running | migrated | partial_migrated | novel | aborted
- novel = operator action (not error in UI). aborted = resumable from MinIO checkpoint.

## GitHub OAuth (single-shot rule)
- Implement in ONE atomic PR: app config, /auth/github, callback, session/token storage, logout.
- GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET from .env. Never hardcode.

## Payments
- Mollie. MOLLIE_API_KEY from .env. Confirm payment by GET to Mollie API on webhook callback.

## Secrets / data
- SQLite name from .env. Dev own .env + DB. Never share dev/prod.
- Odoo keys in Vault. DB stores references only. SUPERADMIN_KEY in apps/superadmin/.env (key-only).
- Never log secrets, tokens, credentials.

## Frontend build (portal, superadmin, web)
- Vue/Vite. vite build / vite dev / vitest run.

## Git
- Conventional Commits. Work only in your worktree. Never touch main. Never push.
- Integrator owns merges. ludo-agent merges before ludo-app.

## Integrity gates
- typecheck, lint, build, unit tests, Contract A conformance, Contract B SSE checks, e2e async smoke.
```

### `ludo-agent/CLAUDE.md`
```md
## What this is
- Python 3.12. FastAPI + Typer CLI share one core. MinIO + SQLite+FTS5 + git memory.
- LLM: Claude primary (OAuth ~/.claude/.credentials.json), OpenAI/Groq fallback.
- Zero per-action confirmations. Safety via dry-run + SafetyGate middleware.

## Endpoints
- Existing: GET /sessions, /sessions/{id}, /sessions/{id}/events (SSE), /sessions/{id}/safety-events, /blueprints, /healthz
- To build: POST /sessions (202 + session_id, spawns agent async) · POST /sessions/{id}/resume (loads MinIO checkpoint)

## Contract B
- contract/session-event.schema.json = source of truth for every SSE event.
- Permissive validator (additionalProperties: true). schema_version + gate_required:false in every event.
- Schema change → Contract B PR first. Do not add gate logic unless instructed.

## Session hierarchy / terminal states
- Customer session (orchestrator) + N model sessions. multi_model_started/model_started/model_completed on customer session.
- migrated | partial_migrated | novel | aborted. novel = catalogue gap (not crash). aborted = checkpoint-resumable.

## Git / gates
- Conventional Commits. Own worktree only. Integrator merges ludo-agent before ludo-app.
- Gates: unit tests, Contract B self-conformance, POST /sessions smoke, async integration smoke.
```

Agent definition files (`.claude/agents/*.md`) carry YAML frontmatter (name, description, tools, model) + a scoped prompt. `dev-agent` owns the two to-build endpoints; `dev-api` owns job CRUD + approval gate + SSE relay + single-shot GitHub OAuth; `test-e2e` exercises happy + NOVEL + resume flows and asserts events are fire-and-forget (no ack). Mirror the pattern for all remaining agents.

## 17. Integrity gates & schema lifecycle

### Merge-blocking gates
- **ludo-agent:** unit green · Contract B self-conformance · POST /sessions smoke · POST /sessions/{id}/resume smoke.
- **ludo-app:** typecheck/lint/build clean (all 4 apps) · unit per app · Contract A conformance · Contract B SSE handler validation · SSE relay correctness · full job state machine (7 states + resume arc) · no secrets in diff.
- **E2E:** happy (migrated reflected in portal+superadmin) · NOVEL (surfaced distinctly, not error) · resume (aborted → resume → terminal).
- **Hard cascade blocks:** Contract B can't merge if api SSE handler tests red; Contract A can't merge if any frontend conformance red; ludo-agent merges before ludo-app.
- Enforced via Claude Code hooks (pre-commit/pre-merge) + CI (GitHub Actions).

### Schema lifecycle (dev → prod)
- **SQLite (apps/api):** numbered append-only migration files `migrations/NNNN_*.sql`; `_migrations` table tracks applied; run on startup; `-- down:` block per file; no hand-edits outside migrations.
- **ludo-agent SQLite + MinIO:** own stores, never connected by apps/api; same numbered-migration pattern; MinIO bucket via `ensure_bucket()` on startup.
- **Contract A (OpenAPI):** classify each change non-breaking (additive, ship freely) vs breaking (two-phase: add new alongside deprecated → remove next cycle). CI snapshot diff (`snapshots/prod.yaml`); breaking without `BREAKING:` label fails CI.
- **Contract B (JSON Schema):** same classification; permissive validators make additions zero-coordination; `schema_version` bump on breaking; CI snapshot diff (`snapshots/prod-session-event.schema.json`).

---

# CLOSING

## 18. Open questions

- **1€/day subscription** — exact scope, what unlocks vs one-off fee, billing cadence (monthly charge confirmed?).
- **Mollie** — VAT/reverse-charge handling in checkout flow.
- **Superdev billing** — superdev pays vs end-customer pays, default?
- **Superdev role** — self-request + approval, or invite-only?
- **Thorough scan** — paid add-on or free?
- **Transactional vs Mautic split** — which mails go where?
- **Hosting** — own infra vs Simplify-ERP SPC for the portal itself?
- **`apps/api` stack** — backend language/framework still TBD (Vue/Vite confirmed for frontends; Python 3.12 for ludo-agent).
- **`web` + `portal` shared `packages/ui`?** — or fully independent styling?
- **MinIO in production** — self-hosted container vs S3-compatible cloud (e.g. Hetzner Object Storage)?
- **Job queue / broker** — **resolved (0.2): a broker IS used.** apps/api enqueues jobs onto **Redis Streams via SAQ** (recommended, pending final confirm); the agent consumes as an internal worker and publishes lifecycle events back. This supersedes the earlier "no queue, direct `POST /sessions`" note (that was the stub). Internal-only; not BullMQ. Tracked [#78](https://github.com/euroblaze/ludo-flywheel/issues/78) / [#88](https://github.com/euroblaze/ludo-flywheel/issues/88) / [euroblaze/ludo #413](https://github.com/euroblaze/ludo/issues/413).

## 19. Out of scope (v1)

- Self-serve deployment automation (download package only).
- Mobile native app (responsive web only).
- Technician-facing UI (email-only for v1).
- LinkedIn OAuth (GitHub only at launch).
- Non-Odoo migrations.
- Decision gates at migration milestones (events informational only; `gate_required` reserved for future).
