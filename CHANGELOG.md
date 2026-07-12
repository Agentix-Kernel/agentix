# Changelog

## 0.5.8 — @tool: default_timeout_seconds kwarg

- `@tool(default_timeout_seconds=...)` / `FunctionTool` attribute — first-class
  declaration of the per-tool dispatch-timeout override the dispatcher already
  reads via `getattr(tool, "default_timeout_seconds", None) or chain_default`.
  None ≡ absent (the `or` fallback), pinned by test. Surfaced by the first
  app-family migration: long-running tools declared it as a class attribute,
  and the factory had no way to carry it without poking the instance.

## 0.5.7 — declarative tool factory (@tool) — #77

- `agentix.tools.factory`: `@tool` decorator builds a `FunctionTool` INSTANCE
  from one async function — name from the function name, description from the
  docstring (or explicit; required), input/output models inferred from type
  hints (`input_model=`/`output_model=` override), `ensure_input` coercion in
  the shell. Declaration errors raise at import time, including the
  mutating-without-verifier invariant (previously registration-time only).
  Dep-carrying tools close over deps via `build_<name>(deps) -> FunctionTool`
  builders; the raw function stays reachable as `.fn`.
- ADDITIVE: the class path is unchanged and kernel builtins keep it; registry/
  dispatcher/safety-gate/`specs()` treat both paths identically (parity test
  pins the spec equality). Exported from `agentix.tools`.
- Docs: tools.md §1 "Two construction paths".
- Enables the app-side migration CRIE 004 T2 (ludo-agent#550, ~35 tools).

## 0.5.6 — turn attribution + payload/handling purity — #86, #87

- `drivers/session.py`: `current_turn_id` ContextVar + `bind_turn`/`unbind_turn`
  beside the session vars; the engine binds the turn identity (stringified
  `turn_index`) around each middleware-chain run. Vendor drivers READ the
  attribution vars — they never define their own (agentix-odoo-driver#4
  consumes this).
- De-brand of kernel-originated payload: `working_memory.py` Field examples
  rewritten vendor-neutral (they render into the LLM-visible record_attempt
  schema — the kernel only HANDLES payloads, it never authors them); stale
  `OdooClient` comments in `retry.py`/`huble.py`/`tools/base.py` generalised.
- Purity gate hardened: vendor model-name tokens (`res.company`, `res.partner`,
  `account.move`, `sale.order`) added — they carried no brand substring and
  slipped the gate once.
- Docs: seams.md "Division of responsibilities — payloads vs. handling"
  (canonical rule + capability table + decision records); drivers.md §7 codifies
  the two capacity gates (gate A model calls / gate B vendor per-target
  semaphore, never nested) and the turn-attribution contract.

## 0.5.5 — the driver midlayer (tools primitives + resilience) — #79

- `agentix.tools.primitives` (pure, stdlib-only): `chunk`/`batched` (lazy
  variant yields lists), `fingerprint_dict` (sha256 of the sort_keys/default=str
  JSON dump — serialization params are the contract), `extract_json_object`
  (tolerant JSON-from-LLM: fence-strip + first balanced object; the former
  adversarial `_parse_verdict`, now shared), `aggregate_by_key` (count-desc,
  first-seen ties).
- `agentix.tools.resilience` (async, kernel-silent): `TransientRetry` strike
  ledger (strikes persist across calls; `reset()` on domain progress; distinct
  from the provider-call Retry middleware — docstrings cross-reference),
  `halve_on_timeout` + `HalvingExhausted`, `bisect_on_failure` recursion
  skeleton with the `on_failure` escape hatch. Policy is caller-supplied
  callbacks; the kernel never calls up and never logs from these helpers.
- `drivers/adapters/adversarial.py` re-points to `extract_json_object`
  (behavior identical; `_parse_verdict` deleted).
- Docs: tools.md new §8 "Primitives — the driver midlayer" (old §8–§12 →
  §9–§13); seams.md midlayer note (mechanism/policy line as callback params).
- Not extracted (recorded): the app AST spike tools stay app-side
  (tools/spike boundary statement; no second consumer — revisit when one
  appears); transient-marker policy, no-progress gates, per-item failure-index
  parsing, quarantine vocabulary, cache key schemes.


## 0.5.4 — terminology: safety_events.type, append_to_log(type=)

- Schema v15: `safety_events.kind` column renamed to `type` (SQLite RENAME
  COLUMN; index follows). `append_safety_event(type=)`, `count_safety_events
  (type=)`, `SafetyType` / `KERNEL_SAFETY_TYPES` (ex `SafetyKind` /
  `KERNEL_SAFETY_KINDS`). `MemoryStore.append_to_log(type=)` (ex `kind=`);
  log.md heading format unchanged. Docs: sqlite_schema.sql, tools.md.

## 0.5.3 — storage drivers phase 3 (file)

- `FileStoreDriver` protocol (`agentix.drivers.file_store`): read/write/append/
  list/exists + `lock()` as a verb + `head_ref()` version pin (None off-git);
  `LocalFileStoreDriver` adapter (`drivers/adapters/local_fs.py`, factory key
  `local-file-store`) owns path containment, fcntl locks and the git pin;
  registry accessor `file_store()`. `MemoryStore` keeps all page semantics;
  `MemoryStore(root)` unchanged, `MemoryStore(driver=...)` injects
  (NextCloud/WebDAV shape proven by test fake). `MemoryLockTimeout` unchanged.

## 0.5.2 — storage drivers phase 2 (relational)

- `RelationalDriver` protocol + `ExecuteResult` (`agentix.drivers.relational`);
  `SqliteRelationalDriver` adapter (`drivers/adapters/sqlite.py`, factory key
  `sqlite-relational`) now owns the aiosqlite connection + PRAGMAs; registry
  accessor `relational()`. `SqliteStore` methods go through the driver verbs;
  `SqliteStore(path)` unchanged, `SqliteStore(driver=...)` injects. sqlite errors
  classify into the driver taxonomy (locked/busy retryable). `EmbeddingCache`
  rides the same driver. `store._db`/`_conn()` remain as the sqlite-dialect
  escape hatch for seam-#10 subclass migrations.

## 0.5.1 — say "type"; storage drivers phase 1 (object store)

- **Breaking rename:** driver `kind` → `type` everywhere — `DriverDescriptor.type`,
  `DriverSpec.type`, `DriverRegistry.by_type()` / `types()` (ex `by_kind`/`kinds`).
- **Storage driver family** (`type="storage"`): `ObjectStoreDriver` protocol +
  `ObjectNotFound` (`agentix.drivers.object_store`), `MinioObjectStoreDriver`
  adapter (`drivers/adapters/minio.py`, factory key `minio-object-store`), registry
  accessors `object_store()` / `object_store_or_none()`. `MinioStore` is now the
  semantic layer over an injected driver; `MinioStore(config)` unchanged for
  consumers. S3 errors now classify into the driver taxonomy. Docs:
  `docs/drivers.md` section 5. Phases 2–3 (relational, file) follow.

## 0.5.0 — Drivers: first-class external-system I/O

The LLM/embeddings layer is re-founded as `agentix.drivers` — one abstraction for
external-system I/O (AI models of any modality; open `kind` vocabulary for future
non-model drivers). The legacy `agentix.llm.*` and `agentix.embeddings` surfaces are
**removed**. Canonical docs: `docs/drivers.md`, `docs/routing.md`.

New: `DriverDescriptor` + `Driver` + per-kind protocols, `DriverRegistry`,
`DriverSpec` config block + `build_drivers()` factory + `register_driver_factory`
(seam #13), HuggingFace STT proof driver (`AudioSource`/`Transcript`/`SttDriver`),
`storage/vector_index.CosineIndex`.

### Rename table (old → new)

| Old (removed) | New | Import from |
|---|---|---|
| `LlmRequest` / `LlmResponse` | `ChatRequest` / `ChatResponse` | `agentix.drivers.chat` |
| `Provider` (protocol) | `ChatDriver` | `agentix.drivers.chat` |
| `LlmError` (`.provider`) | `DriverError` (`.driver`; kwarg `driver=`) | `agentix.drivers.base` |
| `LlmRateLimit` / `LlmUnavailable` / `LlmInvalidRequest` | `DriverRateLimited` / `DriverUnavailable` / `DriverInvalidRequest` | `agentix.drivers.base` |
| `ProviderRouter` / `NoProvidersAvailable` | `ChatFailoverChain` / `NoDriversAvailable` | `agentix.drivers.router` |
| `AnthropicProvider` / `OpenAIProvider` / `GroqProvider` / `HubleProvider` | `*ChatDriver` | `agentix.drivers.adapters.*` |
| `CostRecordingProvider` | `CostRecordingChatDriver` | `agentix.drivers.cost` |
| `bind_session` / `session_scope` / `current_session_id` | unchanged names | `agentix.drivers.session` |
| `llm_capacity` / `configure_llm_capacity` | `driver_capacity` / `configure_driver_capacity` | `agentix.drivers.limiter` |
| `EmbeddingProvider` / `OpenAIEmbeddingProvider` / `HubleEmbeddingProvider` / `CachedEmbeddingProvider` | `EmbeddingDriver` / `*EmbeddingDriver` | `agentix.drivers.embedding` |
| `CosineIndex` | unchanged name | `agentix.storage.vector_index` |
| `agentix.runtime.build_llm_provider(...)` | `build_drivers(...).chat()` (`always_router` → `always_chain`) | `agentix.drivers` |
| `agentix.runtime.build_embedding_provider(cfg, sqlite)` | `build_drivers(cfg, sqlite=...).embedding_or_none()` | `agentix.drivers` |
| `AgentDispatcher(provider=...)` | `AgentDispatcher(driver=...)` | — |

Behavior preserved: failover semantics, cost recording (chat-only; non-token-priced
drivers emit `driver.usage` log lines), activation priority (`enabled_providers`),
capacity limiting (now also covering stt), `model_override` reaching Melious/HUBLE
only. Legacy provider config blocks keep working via `derive_driver_specs`.
