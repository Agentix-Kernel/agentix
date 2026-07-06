# CRIE 003 — repo rename de-brand (ludo-init -> agentix) + isolation verdict

Date: 2026-07-06. Scope: all 7 repos (`agentix`, `ludo-agent`, `ludo-gateway`, `ludo-cli`,
`ludo-webapps`, `ludo-desktop`, `ludo-tests`). Two things: (A) a CRIE isolation verdict on the
kernel vs the gateway, and (B) the cluster-wide de-brand action that followed the repo rename.

## Frame: the rename

`euroblaze/ludo-init` was **renamed to `euroblaze/agentix`** (the hub repo = the kernel). GitHub
redirects the old name and **issue/PR numbers are preserved** (so `ludo-init#N` == `agentix#N`).
On-disk workspace dir + git remote are now `agentix`. Every stale `ludo-init` reference across the
cluster was swept to `agentix`, except the dated `docs/CRIE/00{1,2}_*` records (historical — left
as-written).

## Part A — isolation verdict (agentix <-> ludo-gateway)

The question: do the kernel and the gateway have full isolation? Verdict:

- **Code/runtime isolation: FULL, and guarded.** Gateway never imports `agentix`; agentix never
  imports gateway (grep-verified both ways). Agentix CI runs `test_kernel_purity.py` +
  `test_kernel_standalone.py` — the kernel-app boundary is enforced, not just observed. They meet
  only over the NATS wire (Contract B) + vendored types.
- **Build/dependency isolation: FULL.** Separate `pyproject`/`requirements`/`.venv`; gateway does
  not declare agentix as a dep. No path/editable cross-link.
- **The one coupling (by design):** both vendor byte-identical copies of `ludo_shared`,
  `ludo_internal`, `constants/cluster.yaml`, `contracts/*` — canonical-at-hub (agentix), vendored
  at consumers. Drift is enforced centrally by the `ludo-tests` cross-repo harness wrapping the
  `check_*_drift.py` scripts (correction to an earlier read that drift was un-wired).

## Part B — the de-brand action

Method: full-cluster grep for `ludo-init`, split into two buckets.

- **Bucket 1 (per-repo, no drift risk):** comments, docs, READMEs, script docstrings, licenses.
  Straight `ludo-init -> agentix` sweep, per-repo.
- **Bucket 2 (byte-identical vendored set):** `constants/cluster.yaml`,
  `libs/.../ludo_internal/nats_streams.py`, and the **generated** `_generated.py` (Python) +
  `generated.js/.d.ts` (TS) + `Generated.swift`. Editing these in one repo would drift the others,
  so: edited the 5 canonical sources in agentix (incl. the `gen_shared/gen_ts/gen_swift` header
  strings), **regenerated** the artifacts, and **re-vendored byte-identical** to every consumer.

Verification: all four `check_*_drift.py` pass (config 4/4 · shared 15/15 + codegen 4/4 fresh ·
internal 4/4 · contract 10/10). Vendored artifacts confirmed byte-identical across every
`origin/main` by git-blob SHA (`_generated.py` = one blob everywhere; `cluster.yaml` = one blob).

### `ludo-tests` harness reconciliation

The cross-repo drift harness pointed at the dead `ludo-init` dir. Migrated `LUDO_INIT_REPO ->
LUDO_AGENTIX_REPO` (default dir `agentix`) in `_repo.py` + `Makefile`; dropped the old-var
fallback + breadcrumbs. The drift guard now resolves the renamed hub.

### Landed (7 PRs, squash-merged to default branch)

| Repo | PR |
|---|---|
| agentix | #34 |
| ludo-agent | #528 |
| ludo-gateway | #34 |
| ludo-cli | #9 |
| ludo-webapps | #107 |
| ludo-desktop | #7 |
| ludo-tests | #1 |

In-flight feature branches (`lean-kernel/checkpoint`, `rename/knowledge-to-memory`) were left
untouched — the de-brand was isolated onto branches cut from each default branch (disjoint file
sets, no conflicts).

## Downstream of this analysis (not de-brand, same session)

The isolation question expanded into a design analysis of session + context management under the
generic-kernel + multi-agent + concurrency requirements. Captured as three planning docs on
`agentix` main: [`../session.md`](../session.md), [`../context.md`](../context.md),
[`../isolation.md`](../isolation.md) (the Session triangle + the I1–I7 gather-safe invariants).

## Follow-ups still open

- **Concurrency defects filed** (the I1–I5 invariants' current violations): agentix #38 (cost
  ContextVar leak), #39 (SQLite shared-conn / no busy_timeout), #40 (no global LLM limiter);
  ludo-agent #529 (rename-dir race), #530 (no per-customer budget ceiling).
- **Component inventory (agentix#1):** reserve #20 ContextManager + #21 SessionRuntime.
- **Drift-in-CI:** confirm `agentix` + `ludo-gateway` CI invoke the `ludo-tests` drift harness (or
  a pinned equivalent) — the open half of the isolation follow-up.
