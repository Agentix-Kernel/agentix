"""grep_files — case-sensitive substring/regex search inside the sandbox."""

from __future__ import annotations

import re
import time

import structlog
from pydantic import BaseModel, Field

from agentix.tools._sandbox import _resolved_roots
from agentix.tools.base import Tool, ToolContext, elapsed_ms, ensure_input

log = structlog.get_logger(__name__)


_MAX_HITS = 200


class GrepFilesInput(BaseModel):
    pattern: str = Field(
        ...,
        description="Python regex (re.search semantics). Use anchors / `re.IGNORECASE` flags inline like (?i) for case-insensitivity.",
    )
    root: str = Field(
        default="output",
        description="Sandbox root: 'source' or 'output' (default: 'output').",
    )
    glob: str = Field(
        default="**/*",
        description="Optional glob to restrict search (e.g. '**/*.py'). Defaults to all files.",
    )


class GrepHit(BaseModel):
    path: str
    line: int
    text: str


class GrepFilesOutput(BaseModel):
    hits: list[GrepHit]
    truncated: bool = False
    latency_ms: int = 0


class GrepFiles(Tool):
    name = "grep_files"
    description = (
        "Regex grep across files inside the spike sandbox. Returns a list "
        "of (path, line, text) hits, capped at 200. Use a tighter glob to "
        "narrow the search space if hits are truncated."
    )
    input_schema = GrepFilesInput
    output_schema = GrepFilesOutput
    mutates_target = False
    verifier: str | None = None

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        params = ensure_input(input, GrepFilesInput)
        started = time.perf_counter_ns()
        source_root, output_root = _resolved_roots(ctx)
        base = source_root if params.root == "source" else output_root if params.root == "output" else None
        if base is None:
            raise ValueError(f"grep_files: root must be 'source' or 'output', got {params.root!r}")
        try:
            regex = re.compile(params.pattern)
        except re.error as exc:
            raise ValueError(f"grep_files: invalid regex {params.pattern!r}: {exc}") from exc

        hits: list[GrepHit] = []
        for path in base.glob(params.glob):
            if not path.is_file():
                continue
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        if regex.search(line):
                            hits.append(
                                GrepHit(
                                    path=str(path.relative_to(base)),
                                    line=lineno,
                                    text=line.rstrip("\n")[:300],
                                )
                            )
                            if len(hits) >= _MAX_HITS:
                                break
            except OSError:
                continue
            if len(hits) >= _MAX_HITS:
                break

        out = GrepFilesOutput(
            hits=hits,
            truncated=len(hits) >= _MAX_HITS,
            latency_ms=elapsed_ms(started),
        )
        log.info("spike.grep_files", pattern=params.pattern, root=params.root, hit_count=len(hits))
        return out
