"""read_file — read a text file from inside the spike sandbox."""

from __future__ import annotations

import time

import structlog
from pydantic import BaseModel, Field

from agentix.tools._sandbox import assert_readable
from agentix.tools.base import Tool, ToolContext, elapsed_ms, ensure_input

log = structlog.get_logger(__name__)


_MAX_BYTES = 200_000  # 200 KB — large customer modules rarely have files this big


class ReadFileInput(BaseModel):
    path: str = Field(
        ...,
        description=(
            "Absolute or relative path to read. Must resolve INSIDE the spike's "
            "source-root or output-root. Symlinks are followed; sandbox check "
            "applies to the resolved target."
        ),
    )


class ReadFileOutput(BaseModel):
    path: str
    content: str
    bytes: int
    truncated: bool = False
    latency_ms: int = 0


class ReadFile(Tool):
    name = "read_file"
    description = (
        "Read the text content of a single file inside the spike sandbox "
        "(--source-path or --output-path). Truncates at 200 KB. Use with "
        "glob_files / grep_files for discovery first."
    )
    input_schema = ReadFileInput
    output_schema = ReadFileOutput
    mutates_target = False
    verifier: str | None = None

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        params = ensure_input(input, ReadFileInput)
        started = time.perf_counter_ns()
        target = assert_readable(ctx, params.path)
        if not target.is_file():
            raise FileNotFoundError(f"read_file: {target} is not a regular file")
        raw = target.read_bytes()
        truncated = len(raw) > _MAX_BYTES
        text = raw[:_MAX_BYTES].decode("utf-8", errors="replace")
        out = ReadFileOutput(
            path=str(target),
            content=text,
            bytes=len(raw),
            truncated=truncated,
            latency_ms=elapsed_ms(started),
        )
        log.info("spike.read_file", path=str(target), bytes=len(raw), truncated=truncated)
        return out
