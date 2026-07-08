# LLM providers — MOVED

**Status:** migration pointer · **Scope:** Agentix kernel `[K]` (app-agnostic)

The provider layer was re-founded as the **chat driver family** of the v0.5 driver
framework. This page is deleted in 0.5.0 final; until then it exists only to
repoint inbound links.

- **Canonical doc:** [`drivers.md`](drivers.md) — the driver framework (descriptor,
  registry, per-kind protocols, seam #13), with the chat family in §2 (wire types,
  vendor-SDK adapters incl. the OAuth token sources, cost decorator).
- **Routing** (chain order, failover semantics, policy direction):
  [`routing.md`](routing.md).
- **Code:** `src/agentix/drivers/` (`chat.py`, `adapters/`, `router.py`, `cost.py`,
  `session.py`, `limiter.py`). The old `agentix.llm.*` modules are pure re-export
  shims removed in 0.5.0 final; the rename table ships in the changelog
  (`Provider→ChatDriver`, `LlmRequest/LlmResponse→ChatRequest/ChatResponse`,
  `ProviderRouter→ChatFailoverChain`, `NoProvidersAvailable→NoDriversAvailable`,
  `CostRecordingProvider→CostRecordingChatDriver`,
  `llm_capacity→driver_capacity`, `Llm*` errors → `Driver*` taxonomy).
