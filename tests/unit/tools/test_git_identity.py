"""The agent git-identity seam — registration, defaults, and the revert guard.

The identity is module state (like the sandbox allowlists), so every test
restores the default on exit.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from agentix.tools.spike.git_ops import (
    AgentGitIdentity,
    GitRevert,
    GitRevertInput,
    agent_git_identity,
    register_agent_git_identity,
)


@pytest.fixture(autouse=True)
def _restore_identity() -> Iterator[None]:
    before = agent_git_identity()
    yield
    register_agent_git_identity(before)


def test_default_identity_is_brand_neutral() -> None:
    ident = agent_git_identity()
    assert ident == AgentGitIdentity()
    assert ident.branch_prefix == "agentix/port-spike-"
    assert ident.name == "agentix-agent"
    assert ident.email_domain == "agentix.local"


def test_register_round_trip() -> None:
    app_ident = AgentGitIdentity(branch_prefix="myapp/spike-", name="myapp-agent", email_domain="myapp.local")
    register_agent_git_identity(app_ident)
    assert agent_git_identity() == app_ident


async def test_revert_guard_uses_registered_prefix(tmp_path, monkeypatch) -> None:
    """git_revert refuses branches outside the registered agent namespace."""
    register_agent_git_identity(AgentGitIdentity(branch_prefix="myapp/spike-"))

    # Route the tool at a repo sitting on an operator branch ("main").
    import agentix.tools.spike.git_ops as git_ops

    monkeypatch.setattr(git_ops, "output_root", lambda ctx: tmp_path)

    async def fake_branch(cwd):
        return "main"

    monkeypatch.setattr(git_ops, "_current_branch", fake_branch)

    with pytest.raises(RuntimeError, match=r"not an agent branch.*myapp/spike-"):
        await GitRevert().call(GitRevertInput(sha="deadbeef"), ctx=None)
