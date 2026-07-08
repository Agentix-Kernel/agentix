# Changelog

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
