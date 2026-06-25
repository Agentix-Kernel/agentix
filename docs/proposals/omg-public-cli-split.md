# omg → public transport-only CLI split

Status: approved (planning); in progress — Phase 0 done.
Issues: engine-side `euroblaze/ludo` #463 · public CLI `euroblaze/ludo-omg` #1.

## Decision

- The `omg` CLI moves to a separate **public, open-source** repo `euroblaze/ludo-omg`.
- The engine + worker + read-only API + 3 stores + memory store stay **private** in
  `euroblaze/librado` (this repo).
- `omg` becomes a **transport-only client** (the `kubectl` / `stripe` / `gh` pattern): a network
  client to a LUDO deployment over **Contract A** (REST) + **Contract B** (events) / broker. It
  depends **only on the public contract schemas** — no engine import, and **no Odoo credentials**
  (creds belong to the deployment it points at). Each operator runs `omg` against their **own**
  deployment; access is auth-gated.

## Why transport-only (rejected alternatives)

- **Plain file-move of `cli/`** — rejected: today's `omg` runs the engine in-process (imports
  `core`/`actions`/`tools`/…); a public repo importing a private engine isn't usable by OSS users.
- **Open-core with a private wheel** — rejected: the public repo wouldn't be runnable on its own
  (weak open-source story).
- **Transport-only** — chosen: the natural end-state of #463 (every client reaches the engine
  through the same API). Clean OSS surface + private moat. The protocol being public does not grant
  access — auth does.

## What lives where

| Concern | `ludo-omg` (PUBLIC) | `librado` (PRIVATE) |
|---|---|---|
| CLI commands, help, rendering | ✓ | — |
| Transport client (Contract A REST + Contract B/SSE + job submit) | ✓ | — |
| CLI config (deployment URL + auth token) | ✓ | — |
| Public contract artifacts (`contracts/`) | ✓ (vendored) | source of truth |
| Engine `core` / `actions` / `tools` / `llm` / stores / `memory` / `estimate` / `odoo` | — | ✓ |
| Read-only API server + broker worker | — | ✓ |
| Odoo credentials / customer PII | never | ✓ (vault is apps') |

## Seam: Contract A + Contract B

- **Contract A** (REST) — read introspection now; job-ingress later. Materialize `openapi.yaml`
  from `src/ludo/api/`.
- **Contract B** (events) — the session-event schema.
- Public artifacts are vendored in `ludo-omg/contracts/`; librado's server validates against the
  same schema (the public seam is the only thing both sides share).

## Phasing

- **Phase 0 — DONE (this repo).** Decouple the engine from `cli/`: `cli/_config.py` →
  `ludo/config.py`; `cli/customer_verification.py` → `ludo/actions/verify_customer.py`. The engine
  (`core`/`actions`/`api`/`llm`/`tools`/`storage`/`memory`/`estimate`/`odoo`) now has **zero
  `from ludo.cli` imports** — the precondition for the CLI to leave.
- **Engine-side (#463, private):** Contract B v2 events (B) · broker worker + JobType registry (C) ·
  read-only HTTP introspection parity (D) · apps read client (E).
- **CLI-side (ludo-omg#1, public):** bootstrap (P1) · vendor contracts (P2) · read commands (P3) ·
  write commands via job submit (P4) · cutover (P5).

## Constraints preserved

- apps writes stay **frozen** pending security review; the operator/CLI write path via the broker
  remains the sanctioned, **auth-gated** path.
- **No private git history** is transplanted into the public repo (fresh import).
- During transition, librado keeps an **internal in-process entrypoint** so migrations still run
  while the broker is built; it becomes worker/CI-only at cutover (P5).
