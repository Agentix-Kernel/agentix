# Quickstart — your first agent in 10 lines

## Install

```sh
curl -LsSf https://raw.githubusercontent.com/Agentix-Kernel/agentix/main/scripts/install.sh | AGENTIX_EXTRAS=anthropic bash
source ~/.agentix/env.sh
```

All install variants (the extras matrix, custom `AGENTIX_HOME`, CLI tools,
developer install) live in the [README § Install](../README.md#install) —
single source, not repeated here.

## Write your first agent

```python
import asyncio
from pathlib import Path

from agentix import agentix
from agentix.config import KernelConfig, DriverSpec

cfg = KernelConfig(
    sqlite_path=Path("data/kernel.db"),
    drivers=[DriverSpec(name="llm", driver="anthropic", modality="chat", type="model")],
)

result = agentix.sync.run(
    job_type="answer",
    payload={"question": "What is the capital of France?"},
    cfg=cfg,
)
print(result)
```

Set `ANTHROPIC_API_KEY` in your environment before running.

## Add tools

Tools let the agent take actions — read files, call APIs, query databases.
See [`docs/tools.md`](tools.md) for the `@tool` decorator and the registration pattern.

## Next steps

- [`docs/seams.md`](seams.md) — the 13 extension points for plugging in app domain logic
- [`docs/drivers.md`](drivers.md) — choosing and configuring drivers
- [`docs/vendor-licenses.md`](vendor-licenses.md) — vendor extras and their ToS
- [`docs/kernel-config-reference.md`](kernel-config-reference.md) — all env vars and config keys
