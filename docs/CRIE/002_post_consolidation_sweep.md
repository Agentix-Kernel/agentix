# CRIE 002 — post-consolidation cluster sweep

Date: 2026-06-26. Scope: all 6 repos. Follows CRIE 001 (ludo_shared Python consolidation).
Index issue: euroblaze/ludo-init#11. Method: 3 parallel repo sweeps vs the 001 baseline
(reports only new / still-open items), high-signal findings spot-verified against source.

## Repo -> slug
| dir | slug |
|---|---|
| ludo-agent | euroblaze/ludo |
| ludo-gateway | euroblaze/ludo-gateway |
| ludo-cli | euroblaze/ludo-omg |
| ludo-desktop | euroblaze/ludo-desktop |
| ludo-init | euroblaze/ludo-init |
| ludo-webapps | euroblaze/ludo-flywheel (-> ludo-webapps) |

## Baseline carried from 001 (verified resolved — not re-reported)
- `ludo_shared` (types + broker constants + SSE codec) generated in hub, vendored into
  agent/gateway/cli. Drift guard `check_shared_drift.py`. (PRs still open — see T0.)
- Licenses: agent/gateway/webapps Proprietary; cli/desktop BSL public; hub BSL private.
- Desktop SSE parser fixed (was NDJSON) — fix currently staged, uncommitted.
- R-1 gateway<->webapps parallel control-plane: intentional strangler-fig (flywheel#96), no action.

---

## Themes

### T0 — Land in-flight work (prerequisite, no new code) -> #10
4 open `ludo_shared` PRs (init #7, omg #6, gateway #26, agent #515); staged desktop
`LiveAPIClient.swift`; init `CLAUDE.md` + untracked `docs/proposals/tool-skill-calling.md`
(#503 refactor, same proposal staged in agent). Land these first.

### T1 — Codegen expansion (IE-1 remainder) — biggest lever, P0 -> #8
Python types are generated; TS + Swift are hand-written -> silent drift.
- `ludo-webapps/backend/app/services/notifications.py:21` + `libs/shared/migration_states.js:6`
  — `MIGRATION_STATES` hand-synced py<->js. -> euroblaze/ludo-webapps#101
- `ludo-desktop` `Models/Live.swift:31` — `MigrationState` enum + DTOs hand-kept; events as raw
  `String`. -> euroblaze/ludo-desktop#4
- Hub fix: `scripts/gen_ts.py` + `gen_swift.py` emit types + enums (incl. `MIGRATION_STATES`)
  from `contracts/` + `cluster.yaml`; vendor + drift-guard. Retires R-5a / Swift dup / IE-5.

### T2 — Client know-how docs (IE-3) — P1 -> #9
`docs/contracts-consumer-guide.md` is thin. Consolidate: PKCE flow (S256), client-config
convention (env names, base-URL from `cluster.yaml`, token-storage tiers), SSE resumption
(`Last-Event-ID`/seq), retry/backoff, error taxonomy. Aligns gateway PKCE #30, desktop
base-URL #5, omg retry (ludo-omg #7).

### T3 — Locale reconciliation (C-3, still open) — P1
`cluster.yaml` `backend_default: "de"` / `frontend_default: "en"` vs hardcoded `"en"`:
- gateway `backend/app/models.py:44` `Account.locale default="en"` + `seed.py`. -> euroblaze/ludo-gateway#27
- webapps `backend/app/config.py:98`, `db.py:64,181`. -> euroblaze/ludo-webapps#102
Derive from cluster.yaml; decide the account default explicitly.

### T4 — Per-repo internal dedup & correctness
agent (euroblaze/ludo):
- `_chunk()` duplicated ×6 (tools: load_attachments, rollback, sync_pinned_fields,
  invoke_workflow_action, extract_binary, restore_workflow_states); `_deferred_fk_key()` ×2
  (`tools/load_to_odoo.py:330`, `tools/relink_deferred.py:48`). -> euroblaze/ludo-agent#517
- naive `datetime.now()` (cli/workflow_restoration.py:123,197; actions/verify_customer.py:198,341;
  actions/estimate.py:128) + deprecated `datetime.utcnow()` (actions/port_module.py:468)
  -> `datetime.now(UTC)`. -> euroblaze/ludo-agent#518

gateway:
- `/system/status` registered twice (`routers/health.py:13` AND `routers/system.py:9`, both
  un-prefixed in main.py — last wins); `"not found"` strings repeated (migrations.py:34,49,64;
  events.py:22). -> euroblaze/ludo-gateway#28
- hand-rolled dict projections (store.py:36-45, commerce.py:24-25,152-154) + request models
  without Field/Literal constraints (auth/commerce Req classes). -> euroblaze/ludo-gateway#29

### T5 — Doc freshness / correctness
- agent `README.md:63` says "MIT" but LICENSE is Proprietary; README still describes `omg` as
  shipping here (now `euroblaze/ludo-omg`). -> euroblaze/ludo-agent#516
- webapps `.claude/CLAUDE.md:32`: "schemas live in ludo-gateway/contracts" — canonical is
  `ludo-init/contracts`. -> euroblaze/ludo-webapps#103
- gateway `routers/commerce.py:61` returns 401 for missing `account_id` (caller IS auth'd) —
  should be 403/422. -> euroblaze/ludo-gateway#31

---

## Deferred (tracked, not actioned this pass)
- IE-2b internal NATS `Broker` client relocation to a private-only shared home (agent<->gateway).
- Gateway test-coverage expansion — held under the defer-tests-during-build-out rule.
- webapps TypeScript adoption — design choice; only relevant once T1 lands.

## Realized — Batch A (independent quick wins, merged 2026-06-26)

Tracking fixes first: desktop #4 reopened (only item 1 shipped), #10 closed (T0 complete),
flywheel#41 closed as dup of #101. Then 8 issues across 3 PRs:
- ludo (agent) PR #520 — #516, #517, #518
- ludo-gateway PR #32 — #27, #28, #31
- ludo-webapps PR #104 — #102, #103

**Honest code-savings accounting.** Batch A was mostly *correctness + docs*, not deletion.
Genuine redundancy removed:

| Item | Before | After | Code refs |
|---|---|---|---|
| `_chunk` (agent #517) | 6 identical copies (~12 lines) | 1 canonical `tools/_batch.chunk` | `src/ludo/tools/_batch.py`; was in load_attachments/rollback/sync_pinned_fields/invoke_workflow_action/extract_binary/restore_workflow_states |
| `_deferred_fk_key` (agent #517) | 2 identical copies (~5 lines) | 1 canonical `tools/_keys.deferred_fk_key` | `src/ludo/tools/_keys.py`; was in load_to_odoo + relink_deferred |
| `/system/status` (gateway #28) | registered twice | once (canonical) | `backend/app/routers/{health,system}.py` |
| `"not found"` literals (gateway #28) | 4 inline copies | 1 `errors.NOT_FOUND` | `backend/app/errors.py` |

**Duplication count: 9 redundant sites → 2 canonical helpers + 1 route + 1 const module.**
**Net LOC ≈ flat** (agent commit was 46 ins / 48 del = −2): the removed duplicate logic (~17
lines) is offset by the two small helper files' docstrings/headers + 8 one-line import aliases.
The gateway commerce.py "+153" is almost entirely `ruff format` reflow of pre-existing dict
literals — only 3 lines are real (401→403 + import); excluded from the count above.

The value is the **maintenance win** (a chunking/key-format change now touches 1 file, not 6/2),
not line reduction. The actual cross-language LOC savings land in **Batch B (#8 codegen)** — that
deletes `migration_states.js` + the `MIGRATION_STATES` py↔js hand-sync and the desktop
hand-maintained Swift enum/DTOs.

Correctness/doc items (zero LOC savings): #516 README license, #518 UTC datetimes (4 sites),
#31 401→403 semantics, #27/#102 locale anchoring to cluster.yaml, #103 contracts-source doc.

## Issue index (17 sub-issues under euroblaze/ludo-init#11)
| # | Repo | Issue | Theme | Pri |
|---|---|---|---|---|
| 1 | ludo-init | #8 codegen TS/Swift | T1 | P0 |
| 2 | ludo-init | #9 client know-how docs | T2 | P1 |
| 3 | ludo-init | #10 land in-flight | T0 | P1 |
| 4 | ludo-webapps | #101 MIGRATION_STATES | T1 | P1 |
| 5 | ludo-webapps | #102 locale | T3 | P1 |
| 6 | ludo-webapps | #103 CLAUDE contracts loc | T5 | P1 |
| 7 | ludo-desktop | #4 Swift DTOs + SSE commit | T1/T0 | P0 |
| 8 | ludo-desktop | #5 base-URL config | T2 | P1 |
| 9 | ludo-gateway | #27 locale | T3 | P1 |
| 10 | ludo-gateway | #28 dup /system/status + errors | T4 | P1 |
| 11 | ludo-gateway | #29 response_model + constraints | T4 | P2 |
| 12 | ludo-gateway | #30 PKCE real verify | T2 | P1 |
| 13 | ludo-gateway | #31 checkout 401->403/422 | T5 | P2 |
| 14 | ludo (agent) | #516 README license | T5 | P0 |
| 15 | ludo (agent) | #517 dedup helpers | T4 | P1 |
| 16 | ludo (agent) | #518 datetime UTC | T4 | P1 |
| 17 | ludo-omg | #7 retry/backoff | T2 | P2 |

## Realized — Batch B (cluster-cleanup remainder, 2026-06-26)

The 5 issues left after Batch A (#8, #9, #5, #7, #29). #30 deferred — it's the B2 real-OAuth
lift from ludo-apps (a feature, not a CRIE consolidation item).

- **#8 (T1, P0) — cross-language codegen + #101 fully closed.** `MIGRATION_STATES` made
  canonical in `constants/cluster.yaml :: migration.states`. `gen_shared.py` extended (Python);
  two siblings added — `gen_ts.py` → `libs/ts/ludo_shared/generated.{js,d.ts}`, `gen_swift.py`
  → `libs/swift/LudoShared/Generated.swift` (both client-safe: enums + lifecycle only, no broker
  internals). `check_shared_drift.py` now guards the JS/Swift vendors **and** runs a
  codegen-freshness check (closes IE-6). Hand-synced copies retired: webapps `notifications.py`
  (imports from vendored `ludo_shared`), `libs/shared/migration_states.js` (re-exports the
  generated module), desktop `Models/Live.swift` (hand `MigrationState` enum deleted → generated).
- **#9 (T2, P1).** `docs/contracts-consumer-guide.md` gained PKCE(S256), client-config
  convention (env + `cluster.yaml` `domains` + token-storage tiers), SSE resumption, retry/backoff,
  and the error taxonomy — the spec #5/#7 build against.
- **#5 (P1).** `AuthService.swift` resolves the base URL via new `ClientConfig`
  (env → `UserDefaults` → `cluster.yaml` prod default); stale hardcoded `ludo.euroblaze.de` gone.
- **#7 (P2).** `omg/client.py` retries transient failures (connect/`429`/`5xx`) with bounded
  exponential backoff + jitter (honors `Retry-After`); `stream_events` auto-resumes from the last
  seq via `Last-Event-ID`. Unit-tested.
- **#29 (P2).** `TokenReq`/`EstimateReq`/`CheckoutReq` gained `Field`/`Literal` constraints
  (PKCE-verifier shape, edition/version bounds + no-downgrade, payment-kind enum) → 422 at the
  edge. Dict projections left intentional (ORM/API decoupling).

**LOC (the cross-language savings Batch A pointed here).** ~35 lines of hand-synced lifecycle
duplication removed — 3 copies (webapps py ~8, webapps js ~13, desktop swift ~14) collapse to
**1** canonical `cluster.yaml` line. The generators + guards add ~410 lines of one-time hub
tooling that eliminate the per-language-type drift class permanently (the T1/P0 lever). Honest
net: raw LOC up (tooling), drift-prone hand-maintenance down to zero.

### Still open after Batch B (deferred CRIE optimizations)
- **#30** real PKCE/OAuth verify — B2 GitHub-OAuth lift (feature).
- **IE-2b** internal NATS `Broker` + SSE-encode → private-only shared home (agent⇄gateway),
  ~141 LOC; held (must not vendor into the public clients).
- **IE-4** generic Python infra base (config + JWT/Bearer auth + transient-error classifier),
  agent+gateway; gated behind C-1, modest savings.
- **#29 remainder** dict projections → `response_model` (optional; currently intentional).
- Gateway test-coverage expansion (defer-tests rule); webapps TS adoption (now unblocked — the
  shared types ship a `.d.ts`).

## Realized — Batch C (docs 001/002 remainder, 2026-06-26)

A grounded sweep of the remainder found most items already done or not worth it; the owner
elected to do the substantive + hygiene items anyway. Dispositions + work:

- **C-1 (license flip): already done.** agent + gateway `LICENSE` are the Proprietary notice;
  agent `pyproject` = `LicenseRef-Proprietary`. No code change.
- **IE-4 (infra base): dispositioned — no shareable code.** A two-repo survey found zero real
  duplication: agent config is YAML/multi-context, gateway is env/single-tenant; agent has **no**
  JWT auth (read-only introspection by design); transient-error handling is agent-only +
  provider-specific. A shared "infra base" would be cargo-culting — not created.
- **IE-2b (broker): extracted (~11 LOC) to a private-only home.** New hub package
  `libs/internal/ludo_internal/` (`nats_streams.py`: `ensure_streams` + `connect`), vendored into
  **agent + gateway only** and repointed (`worker/nats.py`, `services/broker.py`); the "MUST match"
  coupling comment is gone. New `scripts/check_internal_drift.py` guards it and **asserts the
  public clients never vendor it** (the boundary check). Honest value: small dedup, but the
  agent↔gateway stream topology can no longer silently diverge.
- **#30 (PKCE/OAuth): implemented.** `routers/auth.py` now does **real S256 PKCE verification**
  (offline-testable DEV path + real GitHub authorization-code exchange in stag/prod, lifted from
  the ludo-apps donor). New `pkce.py` (S256 + a one-time, TTL'd in-memory `PendingAuthStore` —
  single-replica per ADR 0001), `config.py` GitHub creds + `github_oauth_real`. The 501 is gone;
  the synthetic demo path is now DEV-only (stag/prod without real creds still refuses). Tests:
  `test_auth_pkce.py` (S256 verified against the RFC 7636 vector; one-time/expired/mismatch → 400).
- **Gateway test coverage: expanded.** `conftest.py` seeds a tenancy graph + a `bearer` token
  forge; `test_tenancy.py` + `test_commerce.py` assert customer/superdev/superadmin/anon scoping,
  404-not-403 existence-hiding, approve→202, the account-required checkout (#31), and the
  billing-rollup role gate.
- **webapps TS: minimal adoption (Vue retained).** Root `tsconfig.json` + `vue-tsc` `type-check`
  script typecheck the shared libs against the generated `.d.ts` (drift guard between the #8
  generator and its JS consumers); `libs/shared/migration_states.js` is `// @ts-check`'d. **No
  SFC→TS rewrite** — the apps stay Vue 3 + Vite; extending the typecheck to `web-ui/**/*.vue` is a
  documented opt-in next step. (Noted in passing: `libs/web-theme/portal-data.js` keeps its own
  `{id,label}` mock list — a different shape, intentionally not repointed.)

This closes the CRIE 001/002 ledger: every C/R/IE item is now done, dispositioned with evidence,
or explicitly deferred as a feature (none of the latter remain except product features like Mollie).
