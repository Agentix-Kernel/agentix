"""Agentix tool layer — the kernel ``Tool`` protocol, ``ToolContext``, and registry.

Apps register their own tools (and the kernel's generic primitives) against a
``ToolRegistry``. The context carries the three stores + optional app-supplied remote
clients; tools declare ``mutates_target`` + a ``verifier`` so the safety gate can enforce
verify-then-rollback.
"""

from agentix.tools.base import (
    Tool,
    ToolContext,
    ToolSpec,
    elapsed_ms,
    ensure_input,
)
from agentix.tools.registry import ToolConflict, ToolRegistry

__all__ = [
    "Tool",
    "ToolConflict",
    "ToolContext",
    "ToolRegistry",
    "ToolSpec",
    "elapsed_ms",
    "ensure_input",
]
