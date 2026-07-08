# Drivers

**Status:** living doc · **Scope:** Agentix kernel `[K]` (app-agnostic)

**Single source of truth for the driver framework in `docs/`.** Sections 1–7 document
the landed v0.5 subsystem (code: `src/agentix/drivers/`); section 8 is **DIRECTION**.
Neighbouring SSoTs are referenced, never restated (CRIE rule): which model serves a
request — chain order and the routing-policy direction — is [`routing.md`](routing.md);
cost recording and the money budget are [`budgets.md`](budgets.md); the capacity
limiter's isolation invariant is [`isolation.md`](isolation.md) §3 I5.

**A driver is the kernel's first-class unit of external-system I/O** — modular and
developer-programmable. The first family is AI models of any modality (chat,
embedding, stt landed; vision/tts/timeseries designed) from any source (provider API,
gateway, huggingface, local runtime). The base contract is deliberately
system-agnostic: a future database or queue driver registers through the same
descriptor + lifecycle + error taxonomy with zero kernel change — modularity is the
expandability mechanism.

---

## 1. The core contract (`drivers/base.py`)

- **`DriverDescriptor`** (frozen): `name` (unique in the registry), `kind` — an
  **open string vocabulary** (`"model"` today; `"database"`, `"queue"`, … later — no
  kernel enum to amend), `modality` (chat|embedding|vision|tts|stt|timeseries for
  model-kind; None otherwise; validated: model-kind requires one), `source`
  (api|gateway|huggingface|local), `capabilities: frozenset[str]`, `default_model`,
  `pricing_ref` (key into the operator pricing table; **None = this driver's spend is
  not token-priced** — the machine-readable marker the cost story reads, §6).
- **`Driver`** protocol (@runtime_checkable): `descriptor` property + `async aclose()`.
  **Deliberately verb-free** — identity and lifecycle only.
- **Per-kind typed protocols** add the verbs — `ChatDriver.complete(ChatRequest) ->
  ChatResponse`, `EmbeddingDriver.embed(list[str]) -> list[EmbeddingResult]`,
  `SttDriver.transcribe(AudioSource) -> Transcript`. **Rejected alternative:** one
  generic `infer(Any) -> Any` — it erases the typing mypy enforces and forces
  isinstance dances on every caller. Expandability lives in the open `kind`/protocol
  pattern instead (§7 worked example).
- **Error taxonomy** — `DriverError(message, *, driver, retryable=False)`;
  `DriverRateLimited` / `DriverUnavailable` (retryable) vs `DriverInvalidRequest`
  (not). Classification happens once, in the adapter; everything upstream (failover
  chain, Retry middleware) just branches on `retryable`. The legacy `Llm*` names and every
  `agentix.llm.*` / `agentix.embeddings` shim were **removed in 0.5.0**; the rename
  table ships in `CHANGELOG.md`.

## 2. Chat driver family (`drivers/chat.py`, `drivers/adapters/`)

- Canonical wire types: `ChatRequest`/`ChatResponse` (ex-`LlmRequest`/`LlmResponse`,
  field-identical) + `ToolSpec`/`tool_to_spec`.
- Adapters use vendor SDKs **directly** (a locked decision — no translation-layer
  dependency): `AnthropicChatDriver` (API-key + OAuth token sources, re-read
  per-request because externally managed OAuth tokens rotate),
  `OpenAIChatDriver`, `GroqChatDriver`, `HubleChatDriver` (gateway,
  `source="gateway"`, reports its own billed cost in `raw["cost_usd"]`).
- `ChatFailoverChain` (`drivers/router.py`, ex-`ProviderRouter`) — ordered
  first-success failover, itself ChatDriver-compatible; semantics canonical in
  [`routing.md`](routing.md) §2.
- `CostRecordingChatDriver` (`drivers/cost.py`) — the chat cost decorator; recording
  semantics canonical in [`budgets.md`](budgets.md) §3.
- The dispatcher consumes a `ChatDriver` (constructor kwarg `driver=`).

## 3. Embedding driver family (`drivers/embedding.py`)

`EmbeddingDriver` protocol + `OpenAIEmbeddingDriver` / `HubleEmbeddingDriver`,
fronted by `CachedEmbeddingDriver` over the SQLite `EmbeddingCache`
(sha256(model‖text) keys — swapping backends can't return stale vectors). Cosine
ranking is **not** a driver concept: `CosineIndex` lives in
`agentix.storage.vector_index`. What gets embedded is the memory layer's decision
([`memory.md`](memory.md) §4).

## 4. STT — the proof modality (`drivers/speech.py`, `adapters/hf.py`)

`AudioSource` (raw bytes + MIME type) in, `Transcript` out — a request shape that
**cannot be smuggled through `ChatRequest`**, proving the base abstraction isn't
secretly chat-shaped. `HfSttDriver` speaks the HuggingFace Inference API
(`source="huggingface"`, default `openai/whisper-large-v3`, `HF_TOKEN` env or
`api_key_env`): one POST per call, 503-with-`estimated_time` (cold model loading)
classified retryable, `transport=` kwarg as the no-network test seam. Its pricing is
per-second — `pricing_ref=None`, see §6.

## 5. Registry, config, factory — seam #13

- **`DriverRegistry`** (`drivers/registry.py`, ToolRegistry house style): `register`
  (strict, `DriverConflict`) / `try_register` (lenient, log+skip); lookup by `name`
  or the typed accessors `chat()` / `embedding()` / `embedding_or_none()` / `stt()`.
  Default-per-modality is **pure lookup, explicitly not routing policy**: first
  registered wins unless `default=True` says otherwise. `aclose_all()` closes
  everything, logging instead of raising — shutdown must complete.
- **`DriverSpec`** (`config.py`) — one declared instance: `name`, `driver` (builtin
  factory key or dotted path `pkg.mod:Class`), `kind`, `modality`, `model`,
  `base_url`, `api_key_env` (**the env-var NAME, never a secret** — 12-factor),
  `default`, `options`. `KernelConfig.drivers: tuple[DriverSpec, ...]`; empty →
  `derive_driver_specs(cfg)` maps the legacy anthropic/huble/melious blocks (via
  `enabled_providers` — the activation SSoT is unchanged). Collapsing those blocks
  into `drivers:` is the v0.6 config migration
  ([`kernel-config-reference.md`](kernel-config-reference.md)).
- **`build_drivers(cfg, sqlite=None, model_override=None, always_chain=False)`**
  (`drivers/factory.py`) — the one composition entry: chat specs compose into one
  registered chat entry (bare driver when single — no chain overhead — else a
  `ChatFailoverChain` in spec order; each wrapped in `CostRecordingChatDriver` when
  `sqlite` is passed), embedding specs build behind the cache, everything else builds
  strictly — an unknown factory key **fails loud** (a misconfigured driver must not
  be silently skipped).
- **Seam #13 — how developers add drivers** (three explicit paths; entry-points
  discovery **rejected**: ambient import side effects defeat the purity gates):
  1. `register_driver_factory("mysql", build_mysql_driver)` at app startup, then
     declare `DriverSpec(driver="mysql", ...)` in config;
  2. `DriverSpec(driver="my_pkg.drivers:MySqlDriver")` — dotted path; constructor
     contract `__init__(*, spec: DriverSpec, api_key: str | None)`;
  3. build the instance yourself and `registry.register(my_driver)`.

## 6. Cross-cutting — honest v0.5 boundaries

- **Cost**: recorded spend = **chat spend** (`CostRecordingChatDriver`, canonical in
  [`budgets.md`](budgets.md)). Embedding and STT calls are NOT written to the session
  cost ledger — `ModelPricing` is strictly per-token and fake per-second numbers
  would corrupt budget enforcement. They emit a structured `driver.usage` log line
  (kind, modality, driver, model, units, bound session id) so the spend stays
  visible. The kind-agnostic recorder keyed on `pricing_ref` + unit normalization is
  DIRECTION (budgets.md).
- **Capacity**: one process-global semaphore (`drivers/limiter.py`,
  `driver_capacity()`, default 8, per event loop — isolation.md I5) now covers chat
  AND stt calls (embedding wrapping is DIRECTION with per-kind limits).
- **Session attribution**: `current_session_id` / `bind_session` / `session_scope`
  live in `drivers/session.py` — modality-agnostic; non-chat drivers read the
  ContextVar for log attribution.

## 7. Worked example — a database driver (paper only)

Proof the abstraction holds beyond AI models, shipped as documentation (no DB
dependency enters the app-free wheel):

```python
class QueryResult:  ...                       # app-defined wire type

class MySqlDriver:                            # kind="database" — no kernel change
    def __init__(self, *, spec: DriverSpec, api_key: str | None) -> None:
        self._pool = ...                      # dsn from spec.base_url, secret from api_key
        self.descriptor = DriverDescriptor(
            name=spec.name, kind="database", source="local")
    async def query(self, sql: str, params: tuple = ()) -> QueryResult: ...
    async def aclose(self) -> None: ...       # close the pool
```

Declared as `DriverSpec(name="mysql-main", driver="my_pkg.drivers:MySqlDriver",
kind="database", modality="other", base_url="mysql://10.0.99.1:3306/app",
api_key_env="MYSQL_PASSWORD")`. The registry, lifecycle, error taxonomy
(`DriverError(retryable=...)` for deadlocks vs syntax errors) and config discipline
all apply unchanged; only the verb protocol (`query`) is new — defined beside the
driver, not in the kernel.

---

*Everything below is DIRECTION — converged design, not the code today.*

## 8. DIRECTION

- **Routing policy over drivers** — cost-aware/capability-aware candidate ordering,
  escalation tiers, health breakers: [`routing.md`](routing.md) §4/§6–7 (none of it
  landed in v0.5 — the registry default is a lookup, never a choice).
- **Non-chat cost recording** — unit-pricing schema (per-second stt, per-text
  embedding) + a kind-agnostic `CostRecordingDriver` keyed on `pricing_ref`
  ([`budgets.md`](budgets.md)).
- **Per-kind / per-driver capacity limits** (today: one shared semaphore).
- **Remaining modalities** — vision, tts, timeseries protocols + adapters (the stt
  proof establishes the pattern); a kind-generic failover chain (don't generalize
  before a second consumer exists).
- **Config collapse** — fold `anthropic:`/`huble:`/`melious:` into `drivers:` (v0.6).
- **Lifecycle verbs** — `health()` / `warmup()` for local-runtime drivers.
