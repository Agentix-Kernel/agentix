"""apply_patch — apply a unified diff inside the spike output dir.

Shells out to ``git apply`` from the output-root so diffs respect git's
model of the worktree. ``--check`` runs first; only on a clean check does
the real apply land.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import structlog
from pydantic import BaseModel, Field

from agentix.tools._sandbox import output_root
from agentix.tools.base import Tool, ToolContext, elapsed_ms, ensure_input

log = structlog.get_logger(__name__)


class ApplyPatchInput(BaseModel):
    diff: str = Field(
        ...,
        description=(
            "Unified diff content (from `diff -u` or `git diff`). Paths in "
            "the diff must be relative to --output-path. Both `a/` and `b/` "
            "prefixes are stripped (--p1 semantics)."
        ),
    )


class ApplyPatchOutput(BaseModel):
    applied: bool
    files_touched: list[str]
    stderr: str = ""
    latency_ms: int = 0


class ApplyPatch(Tool):
    name = "apply_patch"
    description = (
        "Apply a unified diff to files inside the spike output dir via "
        "`git apply`. Runs `git apply --check` first; on conflict, returns "
        "applied=False with stderr describing why. Paths in the diff must "
        "be relative to --output-path."
    )
    input_schema = ApplyPatchInput
    output_schema = ApplyPatchOutput
    mutates_target = True
    verifier: str | None = "git_status"

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        params = ensure_input(input, ApplyPatchInput)
        started = time.perf_counter_ns()
        cwd = output_root(ctx)

        with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8") as fh:
            fh.write(params.diff)
            patch_path = Path(fh.name)
        try:
            check = await _run_git(["apply", "--check", "-p1", str(patch_path)], cwd=cwd)
            if check.returncode != 0:
                return ApplyPatchOutput(
                    applied=False,
                    files_touched=[],
                    stderr=check.stderr.strip() or "git apply --check failed (no stderr)",
                    latency_ms=elapsed_ms(started),
                )
            apply = await _run_git(["apply", "-p1", str(patch_path)], cwd=cwd)
            if apply.returncode != 0:
                return ApplyPatchOutput(
                    applied=False,
                    files_touched=[],
                    stderr=apply.stderr.strip() or "git apply failed after passing --check",
                    latency_ms=elapsed_ms(started),
                )
        finally:
            patch_path.unlink(missing_ok=True)

        files = _extract_files_from_diff(params.diff)
        out = ApplyPatchOutput(
            applied=True,
            files_touched=files,
            latency_ms=elapsed_ms(started),
        )
        log.info("spike.apply_patch", files=files)
        return out


async def _run_git(args: list[str], *, cwd: Path) -> _Completed:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return _Completed(
        returncode=proc.returncode or 0,
        stdout=stdout.decode("utf-8", errors="replace"),
        stderr=stderr.decode("utf-8", errors="replace"),
    )


class _Completed:
    """Tiny stand-in for subprocess.CompletedProcess (sync) since we're async."""

    def __init__(self, *, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _extract_files_from_diff(diff: str) -> list[str]:
    """Pull the post-image filenames out of a unified diff (b/<path>)."""
    files: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ "):
            payload = line[4:].strip()
            if payload.startswith("b/"):
                payload = payload[2:]
            if payload and payload != "/dev/null":
                files.append(payload)
    return files
