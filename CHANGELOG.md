# Changelog

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
