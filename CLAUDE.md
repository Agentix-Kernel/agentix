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

`src/agentix` carries no app-domain (Odoo/migration) vocabulary in its code surface, and the
kernel wheel ships no branded package. Three CI gates enforce it:
- `tests/unit/test_kernel_purity.py` — AST scan; no forbidden terms in identifiers, string
  literals or imports (incl. `ludo_shared`/`ludo_internal`).
- `tests/unit/test_kernel_standalone.py` — importing the kernel pulls in no `ludo`,
  `ludo_shared` or `ludo_internal` module.
- `tests/unit/test_event_contract_drift.py` — the kernel's native event vocabulary
  (`agentix.event_types`/`agentix.events`) stays equal to `contracts/session-event.schema.json`
  without importing a generated package.

Apps plug in via the 13 seams — canonical catalog in `docs/seams.md`: `KernelConfig` subclass,
`SafetyGate` hooks (`rollback`/`_resolve_contract`/`_derive_verifier_fields`), the dispatcher's
`TerminationPolicy`/`DispatchGuard`, `Tool`/exception `to_error_details()`, `ToolContext`
handles, the `register_allowed_hosts`/`register_allowed_binaries` allowlist extenders, skills,
the `MemoryMaintain` middleware slot, storage subclassing, the event-bus sink, driver
registration (`DriverRegistry.register`/`register_driver_factory`/`DriverSpec`), and the
idempotency/resume-key provider (design seam).

## Layout

- `src/agentix/` — the kernel package (`core/`, `drivers/` — the external-system I/O
  abstraction (chat/embedding/stt families; `llm/` + `embeddings.py` are migration shims
  removed in 0.5.0 final), `tools/`, `skills/`, `a2a/`, `storage`, `config.py`, `runtime.py`).
- `docs/` — kernel docs: `seams`, `async`, `sync`, `engine`, `drivers`, `routing`, `context`,
  `session`, `isolation`, `tools`, `skills`, `memory`, `budgets`, `a2a`, `eval`, `contracts`,
  `kernel-config-reference`, `sqlite_schema.sql`, + `contracts-consumer-guide.md`. The kernel
  overview lives in `README.md`.
- `contracts/` · `constants/` · `templates/` · `libs/` · `scripts/` — shared vendoring machinery
  (consumers vendor; never imported by the kernel, never in the wheel).
- `tests/` — kernel unit + integration; includes the three purity/drift gates above.

## Workflow

- Python **3.12** + **uv**. `ruff` format/lint + `mypy` clean before any PR.
- Run tests only when explicitly asked (they are heavy); the kernel unit surface runs with
  `PYTHONPATH=src pytest`.
- Kernel env vars the runtime reads: see `docs/kernel-config-reference.md`.
