"""write_file — write text to a file inside the spike output dir.

Mutating tool: declares ``verifier="git_status"`` so SafetyGate can confirm
the write actually changed the working tree before the agent moves on.
"""

from __future__ import annotations

import time

import structlog
from pydantic import BaseModel, Field

from agentix.tools._sandbox import assert_writable
from agentix.tools.base import Tool, ToolContext, elapsed_ms, ensure_input

log = structlog.get_logger(__name__)


class WriteFileInput(BaseModel):
    path: str = Field(
        ...,
        description=(
            "Absolute or relative path to write. Must resolve inside the spike's "
            "--output-path. Parent directories are created if missing."
        ),
    )
    content: str = Field(
        ...,
        description="Full file content to write. UTF-8 encoded. Overwrites if file exists.",
    )


class WriteFileOutput(BaseModel):
    path: str
    bytes: int
    created: bool
    latency_ms: int = 0


class WriteFile(Tool):
    name = "write_file"
    description = (
        "Write text to a file inside the spike output dir (creates parent dirs). "
        "Use this for small files (manifest, security CSV, fresh views). For "
        "edits to existing files prefer apply_patch — git diff stays clean."
    )
    input_schema = WriteFileInput
    output_schema = WriteFileOutput
    mutates_target = True
    verifier: str | None = "git_status"

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        params = ensure_input(input, WriteFileInput)
        started = time.perf_counter_ns()
        target = assert_writable(ctx, params.path)
        created = not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        encoded = params.content.encode("utf-8")
        target.write_bytes(encoded)
        out = WriteFileOutput(
            path=str(target),
            bytes=len(encoded),
            created=created,
            latency_ms=elapsed_ms(started),
        )
        log.info("spike.write_file", path=str(target), bytes=len(encoded), created=created)
        return out
