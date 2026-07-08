# CLAUDE.md — agentix (the kernel)

Guidance for Claude Code in this repo. **agentix** is the reusable, app-agnostic **agentic-app
kernel** (`src/agentix/`) — the frozen API + principles for building agent apps: the deterministic
body + **cognitive escalation**, the four calling verbs (`call`/`consult`/`compile`/`delegate`),
sessions/context/isolation, tools + skills, storage, and the versioned wire contracts. **LUDO is an
app built on this kernel** — the kernel carries no app (Odoo/migration) vocabulary.

This repo also holds the shared cross-repo **machinery** that consumers vendor: `contracts/`
(canonical seams), `constants/cluster.yaml`, `templates/`, `libs/` (`ludo_shared`/`ludo_internal`),
and the `scripts/` generators + drift-checkers.

> **Cross-repo context lives elsewhere.** The cluster hub (shared vocabulary, topology, agentic
> surface, repo map), the product PRD and the cluster-level docs are consolidated in
> **`ludo-agent/docs/cluster/`** (`cluster-hub.md` is the entry point). This file is kernel-only.

## Kernel purity — the one hard rule

`src/agentix` carries no app-domain (Odoo/migration) vocabulary in its code surface. Two CI gates
enforce it:
- `tests/unit/test_kernel_purity.py` — AST scan; no forbidden terms in identifiers/string literals.
- `tests/unit/test_kernel_standalone.py` — importing the kernel pulls in no `ludo` module.

Apps plug in via seams: a `KernelConfig` subclass, `SafetyGate` hooks
(`rollback`/`_resolve_contract`/`_derive_verifier_fields`), the dispatcher's
`TerminationPolicy`/`DispatchGuard`, `Tool`/exception `to_error_details()`, and the
`register_allowed_hosts`/`register_allowed_binaries` allowlist extenders. The kernel's one branded
dependency is the vendored wire-contract package `ludo_shared`/`ludo_internal` (Contract-B types +
NATS constants — data contracts, not app logic).

## Layout

- `src/agentix/` — the kernel package (`core/`, `llm/`, `tools/`, `skills/`, `a2a/`, `storage`,
  `config.py`, `runtime.py`).
- `docs/` — kernel docs: `overview`, `context`, `session`, `isolation`, `tools`, `skills`,
  `memory`, `kernel-config-reference`, `sqlite_schema.sql`, + `contracts-consumer-guide.md`.
- `contracts/` · `constants/` · `templates/` · `libs/` · `scripts/` — shared vendoring machinery.
- `tests/` — kernel unit + integration; includes the two purity gates above.

## Workflow

- Python **3.12** + **uv**. `ruff` format/lint + `mypy` clean before any PR.
- Run tests only when explicitly asked (they are heavy); the kernel unit surface runs with
  `PYTHONPATH=src pytest`.
- Kernel env vars the runtime reads: see `docs/kernel-config-reference.md`.
