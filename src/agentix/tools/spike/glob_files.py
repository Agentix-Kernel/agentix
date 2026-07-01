"""glob_files — find files by glob pattern inside the spike sandbox."""

from __future__ import annotations

import time

import structlog
from pydantic import BaseModel, Field

from agentix.tools._sandbox import _resolved_roots
from agentix.tools.base import Tool, ToolContext, elapsed_ms, ensure_input

log = structlog.get_logger(__name__)


_MAX_RESULTS = 500


class GlobFilesInput(BaseModel):
    pattern: str = Field(
        ...,
        description=(
            "Glob pattern relative to --root (e.g. '**/*.py'). Uses "
            "pathlib.Path.rglob semantics; ** matches recursively."
        ),
    )
    root: str = Field(
        default="output",
        description=(
            "Which sandbox root to search in: 'source' (V15 module, read-only) "
            "or 'output' (V18 port dir). Default: 'output'."
        ),
    )


class GlobFilesOutput(BaseModel):
    matches: list[str]
    truncated: bool = False
    latency_ms: int = 0


class GlobFiles(Tool):
    name = "glob_files"
    description = (
        "Find files by glob pattern inside the spike sandbox. Pass "
        "root='source' to scan the V15 module, root='output' (default) "
        "to scan the V18 port dir. Returns paths relative to the chosen "
        "root, capped at 500 results."
    )
    input_schema = GlobFilesInput
    output_schema = GlobFilesOutput
    mutates_target = False
    verifier: str | None = None

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        params = ensure_input(input, GlobFilesInput)
        started = time.perf_counter_ns()
        source_root, output_root = _resolved_roots(ctx)
        if params.root == "source":
            base = source_root
        elif params.root == "output":
            base = output_root
        else:
            raise ValueError(f"glob_files: root must be 'source' or 'output', got {params.root!r}")
        matches: list[str] = []
        for path in base.glob(params.pattern):
            if not path.is_file():
                continue
            matches.append(str(path.relative_to(base)))
            if len(matches) >= _MAX_RESULTS:
                break
        truncated = len(matches) >= _MAX_RESULTS
        out = GlobFilesOutput(
            matches=matches,
            truncated=truncated,
            latency_ms=elapsed_ms(started),
        )
        log.info("spike.glob_files", pattern=params.pattern, root=params.root, count=len(matches))
        return out
