# Model routing

**Status:** living doc · **Scope:** Agentix kernel `[K]` (app-agnostic)

**Single source of truth for model routing in `docs/`.** Sections 1–3 document the
landed v0.1 routing surface (code: `src/agentix/llm/router.py`, the activation
helpers in `config.py` §3, `runtime.py`'s `build_llm_provider`); sections 4–7 are
**DIRECTION**. Neighbouring SSoTs are referenced, never restated (CRIE rule): the
provider protocol + adapters are [`llm.md`](llm.md) §1–2, cost recording and the
money budget are [`budgets.md`](budgets.md), the per-step window budget is
[`context.md`](context.md).

**Routing = deciding which model serves a given request.** Today that decision is
static (an ordered provider chain with error-driven failover). The direction is a
policy layer that chooses by modality, capability, cost and escalation tier — and
the routed unit is an **AI model of any modality**, not only a chat LLM (§5).

---

## 1. The landed v0.1 chain — ordered failover

One static route, decided at build time:

- **Activation + priority** (`config.py`) — `enabled_providers(cfg)` returns the
  active providers in `_PROVIDER_PRIORITY` order: direct gateway first (no extra
  hop), then HUBLE, then Anthropic; `select_enabled_provider` picks the primary,
  and Anthropic is the last resort when nothing is configured. This is the single
  activation code path — kernel runtime and app config loaders share it so the
  two cannot drift.
- **The factory** (`runtime.py` `build_llm_provider`) — builds the active
  adapters in priority order, wraps each in `CostRecordingProvider` when a store
  is passed ([`budgets.md`](budgets.md) §3), and returns a bare provider for a
  single-entry chain or a `ProviderRouter` for several.
  `always_router=True` forces the router wrapper even for one provider, so
  callers that need the router surface (e.g. `set_failover_callback`) never
  isinstance-branch. `model_override` swaps the Melious/HUBLE model per build;
  the Anthropic fallback model deliberately stays as configured.

## 2. `ProviderRouter` — failover semantics

`llm/router.py`. The router holds the ordered chain and is itself
`Provider`-compatible — callers never know whether they hold one adapter or a
chain.

- Dispatch tries each provider in order; **first success wins**.
- Failover happens only on **retryable** errors (`LlmRateLimit`,
  `LlmUnavailable`); `LlmInvalidRequest` re-raises immediately — a malformed
  request won't get better on the next provider. The taxonomy is classified once
  at the adapter ([`llm.md`](llm.md) §1).
- Every hop can notify an async `FailoverCallback` (constructor arg or
  `set_failover_callback` after construction — the runner attaches a
  session-aware callback once the session exists). Callback failures are
  swallowed: observability must never take down dispatch.
- If the whole chain fails: `NoProvidersAvailable` carries the per-provider
  attempt list.
- `default_model` proxies to the **first** provider — cost telemetry seeds from
  the primary, while actual per-call cost is recorded against `response.model`
  ([`budgets.md`](budgets.md) §3).

Tests: `tests/unit/llm/test_router.py`, `tests/unit/llm/test_build_llm_provider.py`,
`tests/unit/test_config_providers.py`.

## 3. Per-call knobs that exist today

- `LlmRequest.model` — overrides the provider's default model for one call;
  every adapter honours it. This is the only per-call routing lever.
- `LlmRequest` already carries `thinking_enabled`, `thinking_budget_tokens` and
  `reasoning_effort` — signals a routing policy could select on (§6), but
  nothing routes on them today.
- The capacity limiter (`llm/limiter.py`, one process-global semaphore around
  every `complete`) bounds concurrency, not selection
  ([`isolation.md`](isolation.md) §3 I5).

---

*Everything below is DIRECTION — converged design, not the code today.*

## 4. Why a routing layer

- **Cost** — escalations should fall through a cost-ordered cascade
  ([`tools.md`](tools.md) §10; [`budgets.md`](budgets.md) §1): solve cheap first,
  wake the expensive model only when the cheap one can't prove its result.
  Today the chain order is availability-driven, not cost-driven.
- **Fit** — a request that needs tool use, thinking blocks or a large window
  should never reach a model that lacks the capability, and a trivial
  classification should never occupy a frontier model.
- **Resilience** — failover today is error-driven only; a health-aware router
  stops sending traffic to a degraded provider before the errors arrive.

## 5. The routed unit is a model, not an LLM

The kernel's routing vocabulary must not assume chat completion. The unit of
routing is an **AI model of any modality** — chat/completions LLMs, but equally
time-series models (industrial forecasting), vision, TTS, STT, embeddings — from
a wide variety of sources: provider APIs, gateways, HuggingFace hub models,
local runtimes.

- **`ModelDescriptor`** — the registry entry a route resolves to:
  - `modality`: `chat | embedding | vision | tts | stt | timeseries | …`
  - `source`: `api | gateway | huggingface | local`
  - `capabilities`: tools, thinking, structured output, context window, languages
  - pricing reference into the operator table
    ([`kernel-config-reference.md`](kernel-config-reference.md))
- Today's `Provider` protocol is the **chat-modality adapter family**; other
  modalities get their own thin protocols behind the same descriptor registry.
  The embeddings path (`build_embedding_provider`, `HubleConfig.embedding_model`)
  is the existing second modality — it folds into the registry rather than
  staying a parallel ad-hoc path.

## 6. The routing-policy seam

A request descriptor in, a ranked candidate list out:

- **In:** modality + capability requirements + tier/effort signals
  (`reasoning_effort`, thinking budget) + remaining money budget.
- **Out:** ordered candidates the dispatcher tries with today's §2 failover
  semantics — policy chooses the order, the router keeps the mechanics.
- Policies, composable:
  - **Cost-aware preference** — cheapest model that satisfies the request
    (the pricing table already exists; this is the v0.2 item flagged in
    [`llm.md`](llm.md) §4).
  - **Escalation ladder** — the cognitive-escalation cascade picks a bigger
    model only when a step can't prove its result ([`tools.md`](tools.md) §10).
  - **Budget-pressure degradation** — near the session cap, prefer cheaper
    candidates before the compress-before-abort path fires
    ([`budgets.md`](budgets.md) §4).
- The policy is a **kernel seam** ([`seams.md`](seams.md)): the kernel ships a
  default (today's static priority order); an app may substitute its own policy
  without touching the router mechanics.

## 7. Health + capability failover

- **Capability mismatch is a pre-dispatch check**, not an upstream error: the
  descriptor says the model lacks tool use / thinking / the window size, so the
  policy never nominates it.
- **Health-aware routing** — circuit-break a provider that is failing or
  degraded (latency, error rate from the failover callback stream) instead of
  paying an error round-trip per request.

## 8. Open decisions

- [ ] `ModelDescriptor` shape + where the registry lives (config-declared vs
  code-registered vs both).
- [ ] Non-chat modality protocols: one generic `infer()` surface vs per-modality
  protocols behind the registry.
- [ ] Policy seam signature and its interaction with `TerminationPolicy` /
  middleware order ([`engine.md`](engine.md)).
- [ ] Whether the escalation ladder's model choice lives in the routing policy
  or in the verbs layer ([`tools.md`](tools.md)).
- [ ] Health signal source: failover-callback stream only, or active probes.
