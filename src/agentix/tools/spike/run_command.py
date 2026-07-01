"""run_command — sandboxed shell execution restricted to an allowlist.

Allowlist enforced: only generic verifiers (python compile, xmllint, pylint,
pytest, ruff, …) are on the kernel default; apps register additional binaries
via :func:`register_allowed_binaries` (the migration app adds ``odoo-bin`` /
``odoo``). Arbitrary shell is intentionally disabled — the agent calling
unlisted binaries is a failure signal worth surfacing.

The agent gets returncode + stdout + stderr as the tool result. Test runners
that exit non-zero on failure are the verifier signal — the agent is
expected to read the stderr and adjust its next patch.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable

import structlog
from pydantic import BaseModel, Field

from agentix.tools._sandbox import output_root
from agentix.tools.base import Tool, ToolContext, elapsed_ms, ensure_input

log = structlog.get_logger(__name__)


# Generic verifier/inspection binaries only. Apps extend via
# ``register_allowed_binaries`` — no app runtime (e.g. odoo-bin) in the kernel.
_ALLOWED_BINARIES: set[str] = {
    "python",
    "python3",
    "xmllint",
    "pylint",
    "pyflakes",
    "ruff",
    "pytest",
    "ls",
    "cat",
}
_DEFAULT_TIMEOUT_S = 60.0
_MAX_TIMEOUT_S = 300.0
_OUTPUT_CAP_BYTES = 32_000


def register_allowed_binaries(binaries: Iterable[str]) -> None:
    """Extend the run_command binary allowlist (app-called at startup)."""
    _ALLOWED_BINARIES.update(binaries)


class RunCommandInput(BaseModel):
    binary: str = Field(
        ...,
        description=(
            "Executable name. Must be in the allowlist: python, python3, "
            "xmllint, pylint, pyflakes, ruff, pytest, ls, cat, plus any the "
            "app registers. No shell, no pipes, no globbing — pass args explicitly."
        ),
    )
    args: list[str] = Field(
        default_factory=list,
        description="Command arguments. Each list element becomes one argv entry; no shell expansion.",
    )
    timeout_s: float = Field(
        default=_DEFAULT_TIMEOUT_S,
        ge=1.0,
        le=_MAX_TIMEOUT_S,
        description="Wall-clock timeout per invocation. Default 60s, max 300s.",
    )


class RunCommandOutput(BaseModel):
    binary: str
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    truncated: bool = False
    timed_out: bool = False
    latency_ms: int = 0


class RunCommand(Tool):
    name = "run_command"
    description = (
        "Run a verifier or test binary inside the spike output dir. Allowlist: "
        "python, python3, xmllint, pylint, pyflakes, ruff, pytest, ls, cat, plus "
        "any binaries the app registers. Args go in the `args` list (no shell "
        "expansion). Use this to verify your edits: `python -m py_compile <file>` "
        "for syntax, `xmllint --noout <file>` for view XML."
    )
    input_schema = RunCommandInput
    output_schema = RunCommandOutput
    # Not flagged mutates_target — running a verifier doesn't change the
    # working tree. write_file / apply_patch / git_commit are the only
    # mutators in the spike's tool catalog.
    mutates_target = False
    verifier: str | None = None

    async def call(self, input: BaseModel, ctx: ToolContext) -> BaseModel:
        params = ensure_input(input, RunCommandInput)
        if params.binary not in _ALLOWED_BINARIES:
            raise ValueError(
                f"run_command: binary {params.binary!r} not in allowlist "
                f"({sorted(_ALLOWED_BINARIES)}); reject before agent reasoning derails"
            )
        started = time.perf_counter_ns()
        cwd = output_root(ctx)
        argv = [params.binary, *params.args]
        log.info("spike.run_command.starting", argv=argv, cwd=str(cwd))
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timed_out = False
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=params.timeout_s)
        except TimeoutError:
            timed_out = True
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            stdout, stderr = await proc.communicate()

        stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
        stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""
        truncated = False
        if len(stdout_text) > _OUTPUT_CAP_BYTES:
            stdout_text = stdout_text[:_OUTPUT_CAP_BYTES] + "\n…(truncated)"
            truncated = True
        if len(stderr_text) > _OUTPUT_CAP_BYTES:
            stderr_text = stderr_text[:_OUTPUT_CAP_BYTES] + "\n…(truncated)"
            truncated = True

        out = RunCommandOutput(
            binary=params.binary,
            args=list(params.args),
            returncode=proc.returncode if proc.returncode is not None else -1,
            stdout=stdout_text,
            stderr=stderr_text,
            truncated=truncated,
            timed_out=timed_out,
            latency_ms=elapsed_ms(started),
        )
        log.info(
            "spike.run_command.finished",
            argv=argv,
            returncode=out.returncode,
            timed_out=timed_out,
        )
        return out
