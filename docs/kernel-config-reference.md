# Kernel config reference

The kernel takes a *resolved* `KernelConfig` (apps own YAML/env loading — see
`config.py`). It does, however, read a handful of environment variables directly
at driver-construction time, mostly as fallbacks when the corresponding
`KernelConfig` field is unset. This is the single canonical list.

## Env vars the kernel reads

| Env var | Read by | Purpose / fallback semantics |
|---|---|---|
| `MELIOUS_BASE_URL` | `drivers/factory.py` | Melious base URL when `melious.base_url` is unset. |
| `MELIOUS_API_KEY` | `drivers/factory.py` | Melious key when `melious.api_key` is unset. |
| `LLMHUB_URL` | `drivers/adapters/huble.py` | HUBLE gateway URL fallback (`huble.base_url`). |
| `LLMHUB_API_KEY` | `drivers/adapters/huble.py` | HUBLE key fallback (`huble.api_key`). |
| `GROQ_API_KEY` | `drivers/adapters/groq.py` | Groq chat key. |
| `OPENAI_API_KEY` | `drivers/factory.py`, `drivers/embedding.py` | Enables the OpenAI embedding fallback when HUBLE embeddings aren't configured. |
| `HF_TOKEN` | `drivers/adapters/hf.py` | HuggingFace Inference API token (stt driver) when no `api_key`/`api_key_env` is declared. |
| `AGENTIX_ANTHROPIC_BILLING_HEADER` | `drivers/adapters/anthropic.py` | Overrides the OAuth billing header. (The legacy branded alias was removed in agentix 0.3.) |
| `CLAUDE_CODE_OAUTH_TOKEN` | `drivers/adapters/anthropic_auth.py` | Anthropic OAuth token source (1st). |
| `ANTHROPIC_AUTH_TOKEN` | `drivers/adapters/anthropic_auth.py` | Anthropic OAuth token source (2nd). |
| `ANTHROPIC_API_KEY` | `drivers/adapters/anthropic_auth.py` | Anthropic API-key token source (3rd; typical for CI). |

Chat **activation** (which of Melious/HUBLE/Anthropic is live, and in what failover
order) is decided in one place — `agentix.config.enabled_providers` /
`select_enabled_provider`, which also feeds `derive_driver_specs`. Both the driver
factory and app config loaders consume it, so the "which backend is active"
predicate can't drift.

## The `drivers:` block — canonical driver declaration

`KernelConfig.drivers: tuple[DriverSpec, ...]`. Each `DriverSpec`:

| Field | Meaning |
|---|---|
| `name` | Registry instance name (unique). |
| `driver` | Builtin factory key (`anthropic`, `huble`, `melious`, `openai-embedding`, `huble-embedding`, `hf-stt`) or a dotted path `pkg.mod:Class` (seam #13, [`drivers.md`](drivers.md) §5). |
| `kind` / `modality` | `model` + chat\|embedding\|stt today; open vocabulary for future kinds (`database`, …). |
| `model`, `base_url` | Instance settings; adapter defaults apply when unset. |
| `api_key_env` | **The env-var NAME holding the credential — never the secret itself** (12-factor). |
| `default` | Marks the default instance for its modality (else first-declared wins). |
| `options` | Adapter-specific passthrough (hashable key/value pairs). |

**Empty `drivers:` is valid and the default**: `derive_driver_specs` maps the legacy
`anthropic:` / `huble:` / `melious:` blocks onto specs, so existing operator YAML
keeps working unchanged. The `drivers:` block is the canonical form going forward;
collapsing the legacy provider blocks into it is the **v0.6 config migration**.

Example:

```yaml
drivers:
  - name: hf-stt
    driver: hf-stt
    modality: stt
    model: openai/whisper-large-v3
    api_key_env: HF_TOKEN
```

## `KernelConfig.llm_pricing`

Empty `llm_pricing` is valid: any model id missing from the table falls through to
`FALLBACK_PRICING['__unknown__']` in `CostTrackingMiddleware` (over-counts rather
than under-counts). Date-stamped model ids are prefix-matched. See the field
docstring in `config.py` and `core/middleware/cost_tracking.py`. Recorded spend is
chat-only in v0.5 ([`budgets.md`](budgets.md) §3); `DriverDescriptor.pricing_ref =
None` marks non-token-priced drivers.

Cluster-wide secret policy (fail-fast in stag/prod, secret vs publishable) lives in
[`ludo-agent/docs/cluster/env-and-secrets.md`](https://github.com/euroblaze/ludo-agent/blob/main/docs/cluster/env-and-secrets.md);
this page is the kernel-specific list.
