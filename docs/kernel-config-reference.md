# Kernel config reference

The kernel takes a *resolved* `KernelConfig` (apps own YAML/env loading — see
`config.py`). It does, however, read a handful of environment variables directly
at provider-construction time, mostly as fallbacks when the corresponding
`KernelConfig` field is unset. This is the single canonical list.

## Env vars the kernel reads

| Env var | Read by | Purpose / fallback semantics |
|---|---|---|
| `MELIOUS_BASE_URL` | `runtime.build_llm_provider` | Melious base URL when `melious.base_url` is unset. |
| `MELIOUS_API_KEY` | `runtime.build_llm_provider` | Melious key when `melious.api_key` is unset. |
| `LLMHUB_URL` | `llm/huble.py` | HUBLE gateway URL fallback (`huble.base_url`). |
| `LLMHUB_API_KEY` | `llm/huble.py` | HUBLE key fallback (`huble.api_key`). |
| `GROQ_API_KEY` | `llm/groq.py` | Groq provider key. |
| `OPENAI_API_KEY` | `runtime.build_embedding_provider`, `embeddings.py` | Enables the OpenAI embedding fallback when HUBLE embeddings aren't configured. |
| `AGENTIX_ANTHROPIC_BILLING_HEADER` | `llm/anthropic.py` | Overrides the OAuth billing header. **Preferred name.** |
| `LUDO_ANTHROPIC_BILLING_HEADER` | `llm/anthropic.py` | **Deprecated** legacy alias for the above — honoured but warns once; removal target agentix 0.3. Precedence: `AGENTIX_*` > `LUDO_*` > built-in default. |
| `CLAUDE_CODE_OAUTH_TOKEN` | `llm/anthropic_auth.py` | Anthropic OAuth token source (1st). |
| `ANTHROPIC_AUTH_TOKEN` | `llm/anthropic_auth.py` | Anthropic OAuth token source (2nd). |
| `ANTHROPIC_API_KEY` | `llm/anthropic_auth.py` | Anthropic API-key token source (3rd; typical for CI). |

Provider **activation** (which of Melious/HUBLE/Anthropic is live, and in what
failover order) is decided in one place — `agentix.config.enabled_providers` /
`select_enabled_provider`. Both the runtime and app config loaders consume it, so
the "which provider is active" predicate can't drift.

## `KernelConfig.llm_pricing`

Empty `llm_pricing` is valid: any model id missing from the table falls through to
`FALLBACK_PRICING['__unknown__']` in `CostTrackingMiddleware` (over-counts rather
than under-counts). Date-stamped model ids are prefix-matched. See the field
docstring in `config.py` and `core/middleware/cost_tracking.py`.

Cluster-wide secret policy (fail-fast in stag/prod, secret vs publishable) lives in
[`env-and-secrets.md`](env-and-secrets.md); this page is the kernel-specific list.
