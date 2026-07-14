# Token Consumption — agentix kernel

> **Maintenance rule.** When adding or modifying any ChatDriver, cost middleware,
> session schema, or budget parameter, update the relevant section of this file
> in the same commit.

This document maps every kernel code path that consumes, records, or limits LLM
tokens. App-level token entry points (CLI commands, compose loop, diagnose tool)
are documented in `ludo-agent/docs/tokens.md`.

---

## Chat drivers — the token-consuming boundary

Every LLM call flows through a driver that implements:
```python
async def complete(request: ChatRequest) -> ChatResponse
```

### Vendor adapters (`src/agentix/drivers/adapters/vendor/`)

| File | Class | Provider |
|------|-------|----------|
| `anthropic.py` | `AnthropicChatDriver` | Anthropic (Claude); native wire format |
| `openai.py` | `OpenAIChatDriver` | OpenAI; OpenAI wire format |
| `melious.py` | `MeliousChatDriver` | Melious (OpenAI-compat); `_temperature_supported=False` |
| `groq.py` | `GroqChatDriver` | Groq; OpenAI wire format |
| `gemini.py` | `GeminiChatDriver` | Google Gemini; OpenAI-compat |
| `grok.py` | `GrokChatDriver` | xAI Grok; OpenAI-compat |
| `nvidia.py` | `NvidiaChatDriver` | NVIDIA NIM; OpenAI-compat |
| `ollama.py` | `OllamaChatDriver` | Ollama (local); OpenAI-compat |

`MeliousChatDriver`, `GroqChatDriver`, `GeminiChatDriver`, `GrokChatDriver`,
`NvidiaChatDriver`, and `OllamaChatDriver` are all thin subclasses of
`OpenAIChatDriver` that override the endpoint and optionally disable temperature.

### Intrinsic adapter (`src/agentix/drivers/adapters/intrinsic/huble.py`)

`HubleChatDriver` — multi-upstream gateway; routes to any upstream provider.
Used when a HUBLE API key is configured. Returns real `cost_usd` in `response.raw`
when the gateway reports it (preferred over local formula).

---

## Wire types (`src/agentix/drivers/chat.py`, `src/agentix/core/types.py`)

### `ChatRequest`
Fields relevant to token budget:
- `max_tokens: int = 16_384` — output budget per call
- `thinking_budget_tokens: int | None` — extended thinking token allocation
- `cache_control: bool = False` — enables prompt caching (reduces `input_tokens` cost)
- `reasoning_effort: Literal["low", "medium", "high"] | None`

### `ChatResponse`
- `usage: TokenUsage` — populated by every driver from the provider's usage report

### `TokenUsage` (`src/agentix/core/types.py`)
```python
class TokenUsage(BaseModel):
    input_tokens: int = 0    # uncached prompt tokens
    output_tokens: int = 0   # completion tokens
    cached_tokens: int = 0   # prompt cache hits (discounted on cost)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens
```

### `Turn` (`src/agentix/core/types.py`)
```python
class Turn(BaseModel):
    usage: TokenUsage  # accumulates across ALL driver.complete() calls in one turn
    cost_usd: float    # set by CostTrackingMiddleware after the turn completes
```

---

## Cost recording (`src/agentix/drivers/cost.py`)

### `CostRecordingChatDriver.complete(request)`
Wraps any `ChatDriver`. Fires immediately after every successful `driver.complete()`
call — before the turn completes, before middleware runs.

Flow:
1. Calls `self._inner.complete(request)` → `response`
2. Reads `current_session_id` ContextVar; skips if None (logs warning)
3. Cost priority: `response.raw["cost_usd"]` (upstream-reported) → local
   `compute_cost_usd(...)` formula
4. Calls `sqlite.update_session(session_id, input_tokens_delta=..., output_tokens_delta=..., cost_usd_delta=...)` — atomic SQL delta update

This is the single persistence point for all token spend. No other code path
writes to `sessions.total_cost_usd`.

---

## Cost tracking middleware (`src/agentix/core/middleware/cost_tracking.py`)

### `CostTrackingMiddleware.__call__(turn, next_)`
Turn-level telemetry. Does NOT persist to SQLite (that is `CostRecordingChatDriver`'s job).

- Calls `compute_cost_usd(...)` on the completed turn's usage
- Sets `turn.cost_usd`
- Logs `cost.turn_telemetry` with `cache_read_ratio` diagnostic

### `compute_cost_usd(model, input_tokens, output_tokens, cached_tokens, pricing_table)`
```python
uncached = max(0, input_tokens - cached_tokens)
return (
    uncached   * pricing.input_per_million          / 1_000_000
  + cached     * pricing.cached_input_per_million   / 1_000_000
  + output     * pricing.output_per_million         / 1_000_000
)
```

### `ModelPricing`
```python
@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float
    cached_input_per_million: float = 0.0
```

### `FALLBACK_PRICING`
Uses prefix-match on model IDs. The catch-all:
```python
"__unknown__": ModelPricing(1.00, 3.00, 0.10)  # conservative estimate
```
Apps can override via `KernelConfig.llm_pricing` → `LlmPricingConfig.as_table()`.

---

## Token budget middleware (`src/agentix/core/middleware/token_budget.py`)

### `TokenBudgetMiddleware.__call__(turn, next_)`
Runs at the start of each turn. Reads `session.total_cost_usd` from SQLite.

- Warns (log level `warning`) when spend crosses 80% of cap
- At cap: attempts context compression via `ContextManager.compress_if_needed()`
- If compression fails or is unavailable: calls `turn.abort(reason)` and returns
  without raising — the engine persists the aborted turn normally
- Never raises an exception

Constructor parameters:
- `budget_usd: float = 25.0` — per-session cap
- `warn_threshold: float = 0.80` — fraction at which to warn
- `context_manager: ContextManager | None` — optional compression hook

---

## Retry & failover (`src/agentix/core/middleware/retry.py`, `src/agentix/drivers/router.py`)

### `RetryMiddleware.__call__(turn, next_)`
- `max_attempts: int = 3`
- `base_delay_s: float = 0.5`, `max_delay_s: float = 15.0`
- Jittered exponential backoff: `delay = uniform(0, min(max_delay, base * 2^(attempt-1)))`
- `DriverInvalidRequest` — not retryable, re-raises immediately
- `DriverRateLimited`, `DriverUnavailable` — retryable up to `max_attempts`

### `ChatFailoverChain.complete(request)` (`src/agentix/drivers/router.py`)
Chains multiple `ChatDriver` instances. First success wins.
- Non-retryable error from any provider → re-raises immediately
- Retryable error → advances to next provider; fires `on_failover` callback if set
- All providers exhausted → raises `NoDriversAvailable` (non-retryable)

Driver error taxonomy:
| Class | Retryable | Typical cause |
|-------|-----------|---------------|
| `DriverRateLimited` | yes | HTTP 429 |
| `DriverUnavailable` | yes | 5xx, timeout, connection reset |
| `DriverInvalidRequest` | no | malformed payload, bad credentials |
| `NoDriversAvailable` | no | all drivers in chain exhausted |

---

## Agent dispatcher (`src/agentix/core/agent_dispatcher.py`)

### `AgentDispatcher.__call__(turn)`
The tool-use loop. Accumulates token usage across every iteration:
```python
turn.usage.input_tokens  += response.usage.input_tokens
turn.usage.output_tokens += response.usage.output_tokens
turn.usage.cached_tokens += response.usage.cached_tokens
```
Each `driver.complete()` call also triggers `CostRecordingChatDriver` immediately,
so SQLite is updated mid-turn, not just at turn end.

---

## Session & SQLite schema (`src/agentix/core/session.py`, `src/agentix/storage/sqlite_store.py`)

### `Session`
```python
class Session(BaseModel):
    budget_usd: float = 200.0          # per-session cap set at create time
    total_input_tokens: int = 0        # cumulative
    total_output_tokens: int = 0       # cumulative
    total_cost_usd: float = 0.0        # authoritative spend (SQLite is source of truth)
```

### `create_session(sqlite, customer_id, budget_usd=200.0, app_meta=None, ...)`
Mints a new session row in SQLite with the requested `budget_usd`.

### `sqlite_store.update_session(..., input_tokens_delta, output_tokens_delta, cost_usd_delta)`
Atomic SQL: `total_cost_usd = total_cost_usd + ?`. Called by `CostRecordingChatDriver`
after each LLM response.

### `sessions` table
| Column | Type | Notes |
|--------|------|-------|
| `id` | TEXT PK | |
| `customer_id` | TEXT | |
| `budget_usd` | REAL | cap set at session creation |
| `total_input_tokens` | INT | cumulative across all turns |
| `total_output_tokens` | INT | cumulative |
| `total_cost_usd` | REAL | cumulative; authoritative |
| `status` | TEXT | `running` / `paused` / `completed` / `failed` |
| `lease_expires_at` | TEXT | session lease TTL (600s default) |
| `parent_session_id` | TEXT | A2A delegation chain |

### `turns` table
Per-turn token and cost breakdown for audit and debugging:
| Column | Type | Notes |
|--------|------|-------|
| `input_tokens` | INT | this turn's input (sum of all LLM calls in the turn) |
| `output_tokens` | INT | this turn's output |
| `cost_usd` | REAL | this turn's cost |
| `content_ref` | TEXT | MinIO key when content is too large for inline |

---

## Session binding (`src/agentix/drivers/session.py`)

```python
current_session_id: contextvars.ContextVar[str | None]
```
Thread-safe. `CostRecordingChatDriver` reads it to attribute spend.

- `bind_session(session_id)` → returns `Token` (for reset)
- `unbind_session(token)` → resets ContextVar
- `session_scope(session_id)` — async context manager; bind on enter, reset on exit

Apps must call `bind_session` (or use `session_scope`) before any agent turn;
otherwise `CostRecordingChatDriver` logs a warning and skips persistence.

---

## Embedding drivers (`src/agentix/drivers/embedding.py`)

Embedding calls do NOT return `TokenUsage` and are NOT tracked in `total_cost_usd`.

| Class | Provider | Notes |
|-------|----------|-------|
| `OpenAIEmbeddingDriver` | OpenAI | per-request pricing, no token count exposed |
| `HubleEmbeddingDriver` | HUBLE gateway | gateway-managed pricing |
| `CachedEmbeddingDriver` | wraps any driver | SQLite `embedding_cache` prevents re-embedding |

### `embedding_cache` table
```sql
CREATE TABLE embedding_cache (
    key       TEXT PRIMARY KEY,  -- sha256(model || text)
    model     TEXT NOT NULL,
    dim       INT  NOT NULL,
    vector    BLOB NOT NULL,     -- packed little-endian float32
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```
`CachedEmbeddingDriver` calls upstream only on cache miss. Cache hits cost $0.

---

## Kernel config (`src/agentix/config.py`)

### `KernelConfig.budget_usd = 200.0`
Default per-session spend cap. Apps override at `create_session` call time.

### `LlmPricingConfig.as_table()`
Merges `FALLBACK_PRICING` with any model overrides from `ludo.yaml`
`providers.<name>.pricing`. Result passed to `CostTrackingMiddleware`.

### `MeliousConfig.enabled: bool = False`
Must be set to `true` in YAML (`providers.melious.enabled: true`) for Melious to
be selected. Default is `False`; without it the fallback Anthropic spec fires
even when `MELIOUS_*` env vars are set.
