# LLM providers

**Status:** living doc · **Scope:** Agentix kernel `[K]` (app-agnostic)

**Single source of truth for the provider layer in `docs/`.** Everything here is
**landed** (code: `src/agentix/llm/`, `runtime.py`, provider configs in
`config.py`). Cross-cutting wrappers that ride on this layer are owned elsewhere
and referenced in §5; **routing** (which model serves a request — chain order,
failover semantics, the policy direction) is [`routing.md`](routing.md).

---

## 1. The `Provider` protocol + wire types (`llm/base.py`)

- `Provider` — one method that matters: `async complete(LlmRequest) ->
  LlmResponse`. Everything upstream (router, cost recorder, dispatcher) speaks
  this protocol, so decorators compose freely.
- `LlmRequest` / `LlmResponse` — the neutral request/response shapes;
  `ToolSpec` + `tool_to_spec(tool)` convert registered tools into the
  provider-neutral JSON-schema advertisements ([`tools.md`](tools.md) §2).
- **Error taxonomy** — `LlmError(provider, retryable)` with three concrete
  classes: `LlmRateLimit` and `LlmUnavailable` (retryable — the router fails
  over, the Retry middleware backs off) vs `LlmInvalidRequest` (not retryable —
  bail immediately). Classification happens once, at the adapter; everyone
  upstream just reads `retryable`.

## 2. Adapters

Provider SDKs are used **directly** (a locked decision — no translation layer),
so per-provider features stay first-class:

- **Anthropic** (`anthropic.py`) — Claude, incl. thinking blocks and cache
  control. Auth is pluggable via **token sources** (`anthropic_auth.py`): a
  static API key, or re-readable OAuth sources (Keychain /
  `~/.claude/.credentials.json`) — re-read on every request because externally
  managed OAuth tokens rotate ~hourly and a captured-at-init token would 401
  mid-session.
- **OpenAI-compatible** (`openai.py`) and **Groq** (`groq.py`) — fallback
  adapters via their official SDKs.
- **HUBLE gateway** (`huble.py`) — routes the loop through a gateway that
  reports its own cost (which the cost recorder prefers,
  [`budgets.md`](budgets.md) §3).

## 3. Activation + the built chain (`config.py`, `runtime.py`)

- **Which provider is active** is a single code path in `config.py` — kernel
  runtime and app config reports share it (they used to mirror the predicates
  and drift). Melious/HUBLE activate on a plain `enabled` flag; Anthropic on the
  compound "any credential present" predicate (`anthropic_active`).
- **Failover priority** when several are active (`_PROVIDER_PRIORITY`) and the
  chain the factory builds are routing concerns — canonical in
  [`routing.md`](routing.md) §1.
- `build_llm_provider(cfg, sqlite=…)` builds the active adapters in priority
  order, wraps **each** in `CostRecordingProvider` when a store is passed
  ([`budgets.md`](budgets.md) §3), and returns a single provider — the router
  when more than one is active, or always with `always_router=True`.

## 4. The router (`llm/router.py`)

`ProviderRouter` holds the ordered chain and is itself `Provider`-compatible, so
callers never know whether they hold one adapter or a chain. Failover semantics,
per-call knobs and the routing-policy direction (cost-aware, modality-general)
are canonical in [`routing.md`](routing.md) — not restated here.

## 5. Cross-cutting wrappers (owned elsewhere)

| Wrapper | What it does | Canonical doc |
|---|---|---|
| `CostRecordingProvider` (`cost_recorder.py`) | records `(tokens, cost_usd)` at the call boundary; session binding via `session_scope` | [`budgets.md`](budgets.md) §3 |
| capacity limiter (`limiter.py`) | one process-global semaphore around every `complete` | [`isolation.md`](isolation.md) §3 I5 |
| adversarial refute (`adversarial.py`) | the reusable refute pass | [`eval.md`](eval.md) §2 |
| embeddings (`embeddings.py`) | semantic recall, pluggable providers | [`memory.md`](memory.md) §4 |
