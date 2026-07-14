"""Kernel tool registration — the generic primitives Agentix ships.

``register_kernel_tools`` registers the always-on, domain-neutral primitives (read-only
file/web access + the MinIO-backed scratch write). ``register_kernel_module_mode_tools``
registers the mutating sandbox primitives (write/patch/shell/git) — only meaningful
when a writable sandbox boundary is active, so apps opt in for module-port-style work.

Apps compose these onto their registry alongside their own tools (e.g. the migration
app's ``register_builtin_tools`` calls ``register_kernel_tools`` then adds its Odoo tools).
"""

from __future__ import annotations

from agentix.tools.registry import ToolRegistry
from agentix.tools.spike.apply_patch import ApplyPatch
from agentix.tools.spike.git_ops import GitCommit, GitDiff, GitRevert, GitStatus
from agentix.tools.spike.glob_files import GlobFiles
from agentix.tools.spike.grep_files import GrepFiles
from agentix.tools.spike.read_file import ReadFile
from agentix.tools.spike.run_command import RunCommand
from agentix.tools.spike.web_fetch import WebFetch
from agentix.tools.spike.write_file import WriteFile
from agentix.tools.write_to_fs import WriteToFs


def register_kernel_tools(registry: ToolRegistry) -> None:
    """Register the always-on, domain-neutral primitives.

    Read-only file/web access (``read_file``/``glob_files``/``grep_files``/``web_fetch``)
    plus ``write_to_fs`` (MinIO-backed scratch). Safe in any sandbox.
    """
    registry.register(ReadFile())
    registry.register(GlobFiles())
    registry.register(GrepFiles())
    registry.register(WebFetch())
    registry.register(WriteToFs())


def try_register_kernel_tools(registry: ToolRegistry) -> None:
    """Like register_kernel_tools but skips tools already registered.

    Use in plugin contexts where the kernel has already registered its builtins
    before calling plugin.register() — avoids ToolConflict without silencing
    genuine conflicts elsewhere.
    """
    for tool in (ReadFile(), GlobFiles(), GrepFiles(), WebFetch(), WriteToFs()):
        registry.try_register(tool)


def register_kernel_module_mode_tools(registry: ToolRegistry) -> None:
    """Register the mutating sandbox primitives (write/patch/shell/git).

    Caller must have set a writable sandbox boundary before these are dispatched.
    """
    registry.register(WriteFile())
    registry.register(ApplyPatch())
    registry.register(RunCommand())
    registry.register(GitStatus())
    registry.register(GitDiff())
    registry.register(GitCommit())
    registry.register(GitRevert())
