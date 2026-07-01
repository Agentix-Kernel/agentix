"""Kernel primitive tools — generic file / git / shell / web tools.

Deliberately domain-neutral so the agent's reasoning is the variable, not app-specific
helpers. Registered onto a :class:`agentix.tools.registry.ToolRegistry` via
:func:`agentix.tools.builtin.register_kernel_tools` /
:func:`agentix.tools.builtin.register_kernel_module_mode_tools`. Domain-aware parsers
(e.g. the migration app's Odoo Python/XML AST tools) live in the app, not here.
"""

from agentix.tools.spike.apply_patch import ApplyPatch, ApplyPatchInput, ApplyPatchOutput
from agentix.tools.spike.git_ops import (
    GitCommit,
    GitCommitInput,
    GitCommitOutput,
    GitDiff,
    GitDiffInput,
    GitDiffOutput,
    GitRevert,
    GitRevertInput,
    GitRevertOutput,
    GitStatus,
    GitStatusInput,
    GitStatusOutput,
)
from agentix.tools.spike.glob_files import GlobFiles, GlobFilesInput, GlobFilesOutput
from agentix.tools.spike.grep_files import GrepFiles, GrepFilesInput, GrepFilesOutput
from agentix.tools.spike.read_file import ReadFile, ReadFileInput, ReadFileOutput
from agentix.tools.spike.run_command import RunCommand, RunCommandInput, RunCommandOutput
from agentix.tools.spike.web_fetch import WebFetch, WebFetchInput, WebFetchOutput
from agentix.tools.spike.write_file import WriteFile, WriteFileInput, WriteFileOutput

__all__ = [
    "ApplyPatch",
    "ApplyPatchInput",
    "ApplyPatchOutput",
    "GitCommit",
    "GitCommitInput",
    "GitCommitOutput",
    "GitDiff",
    "GitDiffInput",
    "GitDiffOutput",
    "GitRevert",
    "GitRevertInput",
    "GitRevertOutput",
    "GitStatus",
    "GitStatusInput",
    "GitStatusOutput",
    "GlobFiles",
    "GlobFilesInput",
    "GlobFilesOutput",
    "GrepFiles",
    "GrepFilesInput",
    "GrepFilesOutput",
    "ReadFile",
    "ReadFileInput",
    "ReadFileOutput",
    "RunCommand",
    "RunCommandInput",
    "RunCommandOutput",
    "WebFetch",
    "WebFetchInput",
    "WebFetchOutput",
    "WriteFile",
    "WriteFileInput",
    "WriteFileOutput",
]
