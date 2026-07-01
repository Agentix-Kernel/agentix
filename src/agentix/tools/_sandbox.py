"""Filesystem-sandbox helpers for the agent's primitive tools.

Production tools that touch the filesystem (``read_file``, ``write_file``,
``apply_patch``, ``glob_files``, ``grep_files``, ``run_command``, ``git_*``)
must resolve every path against the active sandbox set by
:func:`set_sandbox` (or one of the convenience helpers
:func:`set_module_port_sandbox` /:func:`set_workspace_sandbox`).

Two design properties:

* **Generality** — boundaries are ``(path, writable)`` pairs, so the same
  tool implementations serve module-mode (source RO + output RW) and
  data-mode (workspace RW) without per-mode forks.
* **Async-safe** — boundaries thread via a:class:`contextvars.ContextVar`,
  not via the ``Session`` object (which is a strict pydantic model that
  rejects ad-hoc attributes and would lose state on snapshot/restore).

The "module port sandbox" preset is a convenience wrapper for the
common source-RO + output-RW shape.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from agentix.tools.base import ToolContext


class SandboxError(RuntimeError):
    """Raised when a primitive tool is asked to touch a path outside the sandbox."""


# Backwards-compatible alias for tools that import this name.
SpikeSandboxError = SandboxError


@dataclass(frozen=True)
class SandboxBoundary:
    """One allowed area inside the sandbox.

    ``path`` is resolved (symlinks followed, absolute) at construction
    time; tools compare against this resolved form.
    """

    path: Path
    writable: bool

    @classmethod
    def make(cls, path: str | Path, *, writable: bool) -> SandboxBoundary:
        return cls(path=Path(path).expanduser().resolve(), writable=writable)


_SANDBOX: contextvars.ContextVar[tuple[SandboxBoundary, ...] | None] = contextvars.ContextVar(
    "_ludo_sandbox", default=None
)


@contextmanager
def set_sandbox(boundaries: list[SandboxBoundary]) -> Iterator[None]:
    """Bind a list of sandbox boundaries for the duration of the ``with`` block.

    Every primitive tool inside the block resolves paths against ``boundaries``.
    Reads are allowed inside any boundary; writes only inside writable ones.
    Empty list means "no filesystem access" — every tool call raises.
    """
    token = _SANDBOX.set(tuple(boundaries))
    try:
        yield
    finally:
        _SANDBOX.reset(token)


@contextmanager
def set_module_port_sandbox(*, source: Path, output: Path) -> Iterator[None]:
    """module-port preset — source root RO, output root RW.

    Backward-compatible with the ``set_spike_sandbox`` signature.
    """
    with set_sandbox(
        [
            SandboxBoundary.make(source, writable=False),
            SandboxBoundary.make(output, writable=True),
        ]
    ):
        yield


@contextmanager
def set_workspace_sandbox(workspace: Path, *, extra_readable: list[Path] | None = None) -> Iterator[None]:
    """General data-mode preset — single writable workspace + optional read-only extras.

    Used when the agent loop needs filesystem access for work products
    (e.g. drafts, exports, cached lookups) without the bidirectional
    source/output split of module-mode.
    """
    boundaries = [SandboxBoundary.make(workspace, writable=True)]
    for extra in extra_readable or []:
        boundaries.append(SandboxBoundary.make(extra, writable=False))
    with set_sandbox(boundaries):
        yield


# Backwards-compatible alias — some tools call this name verbatim.
set_spike_sandbox = set_module_port_sandbox


def assert_readable(ctx: ToolContext, path: str | Path) -> Path:
    """Resolve ``path`` and confirm it lives inside any sandbox boundary."""
    target = Path(path).expanduser().resolve()
    boundaries = _require_active_sandbox()
    for b in boundaries:
        if _is_within(target, b.path):
            return target
    raise SandboxError(f"read denied — {target} is outside the active sandbox ({[str(b.path) for b in boundaries]})")


def assert_writable(ctx: ToolContext, path: str | Path) -> Path:
    """Resolve ``path`` and confirm it lives inside a writable sandbox boundary."""
    target = Path(path).expanduser().resolve()
    boundaries = _require_active_sandbox()
    for b in boundaries:
        if b.writable and _is_within(target, b.path):
            return target
    raise SandboxError(
        f"write denied — {target} is not inside any writable sandbox boundary "
        f"({[str(b.path) for b in boundaries if b.writable]})"
    )


def writable_roots(ctx: ToolContext) -> list[Path]:
    """Return all writable boundary roots in the active sandbox.

    Tools like ``git_commit`` need to know where the agent is allowed to
    operate (to find a git repo). When multiple writable roots exist,
    returns them in declaration order.
    """
    return [b.path for b in _require_active_sandbox() if b.writable]


def primary_writable_root(ctx: ToolContext) -> Path:
    """Convenience: return the FIRST writable boundary root.

    Module-mode: this is the output root (where git lives). Data-mode:
    this is the workspace root. Tools that need a single "work here"
    location use this; tools that legitimately span multiple writable
    roots call:func:`writable_roots`.
    """
    roots = writable_roots(ctx)
    if not roots:
        raise SandboxError("no writable boundary in the active sandbox")
    return roots[0]


# Backwards-compatible alias — git_ops + apply_patch call ``output_root``.
def output_root(ctx: ToolContext) -> Path:
    """[Compat] First writable root — module-mode's output dir, data-mode's workspace."""
    return primary_writable_root(ctx)


def _require_active_sandbox() -> tuple[SandboxBoundary, ...]:
    boundaries = _SANDBOX.get()
    if boundaries is None:
        raise SandboxError(
            "sandbox not initialised — wrap the agent loop in "
            "`with set_sandbox([...])` (or `set_module_port_sandbox(...)` / "
            "`set_workspace_sandbox(...)`)"
        )
    return boundaries


def _resolved_roots(_ctx: ToolContext) -> tuple[Path, Path]:
    """[Compat] Return ``(read_root, write_root)`` for module-port-shape sandboxes.

    Raises if the active sandbox doesn't have exactly one RO + one RW
    boundary (which is the module-port preset's invariant).
    """
    boundaries = _require_active_sandbox()
    ro = [b.path for b in boundaries if not b.writable]
    rw = [b.path for b in boundaries if b.writable]
    if len(ro) == 1 and len(rw) == 1:
        return ro[0], rw[0]
    raise SandboxError(
        f"_resolved_roots requires a module-port-shape sandbox (1 RO + 1 RW); found {len(ro)} RO + {len(rw)} RW"
    )


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False
