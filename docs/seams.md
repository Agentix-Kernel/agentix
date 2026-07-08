# Seams — the kernel↔app contact points

The definitive catalog of how a purpose-specific app plugs into the generic kernel.
Everything an app supplies enters through one of these 11 seams; everything else is
kernel-internal. LUDO examples are illustrations of *an* app, not part of the kernel.

## The 11 seams

### 1. Config — `KernelConfig` subclass
`src/agentix/config.py`. A frozen dataclass with the kernel's resolved settings (storage
paths, LLM provider configs, budget). The app subclasses it and appends its own resolved
fields; the kernel runtime factories accept the subclass unchanged.
*LUDO:* `ResolvedConfig` adds source/target ERP credentials + a per-customer registry.

### 2. SafetyGate hooks — subclass 3 methods
`src/agentix/tools/safety.py` (`SafetyGate`). The kernel enforces verify-after-mutate;
the app supplies the domain knowledge via three overrides:
- `rollback()` — undo a mutation whose verification drifted (default: `NotImplementedError`).
- `_resolve_contract()` — per-model verify contract + derived check fields (default: count+sample).
- `_derive_verifier_fields()` — map tool-input fields the verifier can't name-match (default: `{}`).
*LUDO:* `OdooSafetyGate` rolls back via xmlid-scoped unlink and reads its rename-map memory.

### 3. TerminationPolicy — protocol
`src/agentix/core/agent_dispatcher.py` (`TerminationPolicy`): `observe(turn)` +
`terminal_message(turn)`. The app defines what "done" means and can force-terminate the loop.
*LUDO:* terminate once every requested model loaded successfully.

### 4. DispatchGuard — pre-execution veto
`src/agentix/core/agent_dispatcher.py` (`DispatchGuard`): a callable inspecting each pending
tool call; returns a synthesized failure `ToolCallResult` to refuse it, or `None` to allow.
*LUDO:* refuse `drop_field` on FK-protected columns.

### 5. Tool protocol — register domain tools
`src/agentix/tools/base.py` (`Tool`, runtime-checkable protocol: `name`, `description`,
`input_schema`, `output_schema`, `mutates_target`, `verifier`, `async call()`). The app
implements it — no subclassing needed — and registers in the `ToolRegistry`. App exceptions
may expose `to_error_details()` (dispatcher hook) to return structured error payloads.
*LUDO:* ~40 migration tools (extract/load/discover/pin/diagnose…).

### 6. ToolContext injection — opaque app handles
`src/agentix/tools/base.py` (`ToolContext`). `source` / `target` are untyped handles the app
fills with its own clients; the kernel never inspects them. Tools access via
`ctx.require_source()` / `ctx.require_target()`.
*LUDO:* source/target Odoo RPC clients.

### 7. Sandbox allowlists + agent identity — startup extenders
`src/agentix/tools/spike/web_fetch.py` (`register_allowed_hosts`),
`run_command.py` (`register_allowed_binaries`) and `git_ops.py`
(`register_agent_git_identity` — git branch namespace + commit author; the branch
prefix also guards `git_revert`). Kernel defaults cover code-hosting, generic
verifiers and a neutral `agentix-agent` identity; the app extends at startup.
*LUDO:* adds `odoo.com` hosts, the `odoo-bin` binary, and the `ludo/port-spike-`
branch identity.

### 8. Skills — `SkillCatalog(skills_root)`
`src/agentix/skills/catalog.py`. The app points the catalog at its own skill-bundle
directory (Agent Skills standard: `SKILL.md` + manifest + optional `tool.py`). Session
start surfaces name+description cheaply; bodies load on demand (progressive disclosure).

### 9. Middleware chain — append after the kernel order
`KERNEL_MIDDLEWARE_ORDER` + the `Engine(middleware_order=…)` parameter. The kernel ships
the ordered core chain (trajectory, cost, budget, caps, loop-detection, retry, dangling,
safety); the app appends its own middleware after it.
*LUDO:* `MemoryMaintain` (ingest→lint→promote at session end).

### 10. Storage — use or subclass the three stores
`agentix.storage` (`SqliteStore`, `MinioStore`, `MemoryStore`). Use as-is, or subclass to
add app tables/keys — the kernel schema stays untouched.
*LUDO:* `LudoSqliteStore` adds `diagnoses` + `applied_memory_rules` tables.

### 11. Events out — bus sink + neutral envelope
`src/agentix/events.py`: the global `bus` and the neutral `SessionEvent` (6-field
Contract-B envelope; types in `agentix.event_types`). The app registers a global sink to
forward events to its own transport. The kernel knows no broker.
*LUDO:* a NATS forwarder republishes every event to JetStream.

## What the kernel will never contain

- **Domain vocabulary** — no app terms in identifiers or string literals.
- **App transport topology** — no broker URLs, stream names, subjects.
- **Credentials / PII** — the app resolves and injects; the kernel sees opaque handles.

Enforced by three gates in `tests/unit/`:
- `test_kernel_purity.py` — AST scan of `src/agentix/` for forbidden terms (identifiers,
  string literals, imports).
- `test_kernel_standalone.py` — importing the kernel surface pulls in no `ludo.*`,
  `ludo_shared`, or `ludo_internal` module.
- `test_event_contract_drift.py` — the kernel's native event vocabulary stays equal to the
  cross-cluster wire contract (`contracts/session-event.schema.json`) without importing it.
