# Vendor Driver Licenses

Agentix ships a two-tier driver model:

- **Intrinsic drivers** — open-source infrastructure (SQLite, PostgreSQL, MinIO, HuggingFace,
  local filesystem). Their SDKs carry permissive licenses (MIT, Apache 2.0) and impose no
  commercial API ToS on the consumer.

- **Vendor drivers** — commercial AI/LLM APIs. Their SDKs are also open-source, but the
  **underlying API services carry their own Terms of Service** which the consumer must
  independently review and accept before use.

Agentix makes no representations about third-party ToS terms. Always verify current terms
directly with the provider.

## Vendor extras and their ToS

| Extra | Install | SDK | SDK license | API ToS |
|-------|---------|-----|-------------|---------|
| `[anthropic]` | `pip install agentix[anthropic]` | `anthropic` | MIT | https://www.anthropic.com/legal/usage-policy |
| `[openai]` | `pip install agentix[openai]` | `openai` | MIT | https://openai.com/policies/terms-of-use |
| `[groq]` | `pip install agentix[groq]` | `groq` | Apache 2.0 | https://groq.com/terms-of-use |

The `[openai]` extra also enables: **Gemini** (Google AI ToS: https://ai.google.dev/gemini-api/terms),
**Ollama** (https://ollama.com/legal/terms), **Grok/xAI** (https://x.ai/legal/terms-of-service),
**NVIDIA NIM** (https://www.nvidia.com/en-us/data-center/products/ai-enterprise/eula/),
and **Melious** — all use the OpenAI-compatible wire format.

## Intrinsic extras

| Extra | SDK | License |
|-------|-----|---------|
| `[minio]` | `minio` | Apache 2.0 |
| `[hf]` | `huggingface_hub` | Apache 2.0 |
| `[postgresql]` | `asyncpg` | MIT |
