"""AgentCard + Capability — an agent's declarative self-description for A2A.

Pure data + validation, no transport or credentials (see package docstring).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Capability(BaseModel):
    """One thing an agent can be asked to do over A2A.

    ``name`` is the stable local handle a peer names in a ``delegate``. ``subject``
    is the transport address it will eventually be routed on (e.g.
    ``int.<domain>.<account>.<name>``) — ``None`` until W2 wires routing, so the
    card stays useful for discovery before any transport exists.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    subject: str | None = None

    @model_validator(mode="after")
    def _non_empty_name(self) -> Capability:
        if not self.name.strip():
            raise ValueError("capability name must be non-empty")
        return self


class AgentCard(BaseModel):
    """An agent's self-description — the payload of a discovery/INFO reply.

    Declarative only: it says *who* the agent is and *what* it can do, so a peer
    can decide whether and what to delegate. It carries no credentials and no
    trust-zone wiring; authorization + routing are layered on in later A2A
    slices. ``activatable`` marks a key-gated agent that has a deterministic
    fallback when its key is absent.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    version: str = "0"
    capabilities: list[Capability] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    activatable: bool = False

    @model_validator(mode="after")
    def _validate(self) -> AgentCard:
        if not self.name.strip():
            raise ValueError("agent name must be non-empty")
        names = [c.name for c in self.capabilities]
        if len(names) != len(set(names)):
            raise ValueError("capability names must be unique within an agent card")
        return self

    def capability_names(self) -> list[str]:
        return [c.name for c in self.capabilities]

    def has_capability(self, name: str) -> bool:
        return any(c.name == name for c in self.capabilities)

    def capability(self, name: str) -> Capability | None:
        """The named capability, or None. Used by a peer resolving a delegate."""
        for c in self.capabilities:
            if c.name == name:
                return c
        return None
