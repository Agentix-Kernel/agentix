"""write_to_fs — general-purpose blob writer under the session's MinIO prefix.

Used by the agent for anything that doesn't fit another tool: logs,
manual reports, debug dumps. The blob lands under
``blobs/session-artifacts/{session_id}/{relative_key}`` so it's
automatically session-scoped and reaped alongside other session data.
"""

from __future__ import annotations

import time

import structlog
from pydantic import BaseModel, Field

from agentix.storage import MinioStore
from agentix.tools.base import Tool, ToolContext, elapsed_ms, ensure_input

log = structlog.get_logger(__name__)


class WriteToFsInput(BaseModel):
    relative_key: str = Field(..., min_length=1, description="Key suffix under the session prefix.")
    content: str = Field(..., description="UTF-8 text payload to write.")
    content_type: str = "text/plain"


class WriteToFsOutput(BaseModel):
    minio_key: str
    bytes_written: int
    latency_ms: int


class WriteToFs(Tool):
    """Write a UTF-8 text blob to the session-scoped MinIO prefix."""

    name = "write_to_fs"
    description = "Write an arbitrary text blob to MinIO under the current session's artifact prefix."
    input_schema = WriteToFsInput
    output_schema = WriteToFsOutput
    mutates_target = False
    verifier: str | None = None

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        params = ensure_input(input, WriteToFsInput)
        key = MinioStore.key_session_artifact(ctx.session.customer_id, ctx.session.id, params.relative_key)
        started = time.perf_counter_ns()
        body = params.content.encode("utf-8")
        await ctx.minio.put_bytes(key, body, content_type=params.content_type)
        elapsed = elapsed_ms(started)
        log.info(
            "write_to_fs.ok",
            session_id=ctx.session.id,
            key=key,
            bytes=len(body),
            latency_ms=elapsed,
        )
        return WriteToFsOutput(minio_key=key, bytes_written=len(body), latency_ms=elapsed)
