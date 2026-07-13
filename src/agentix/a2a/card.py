"""AgentCard — A2A v1.0 data model (discovery only, no transport).

Pure data + validation.  No transport, credentials or trust-zone wiring —
those land in W1-W3 (epic euroblaze/ludo #492).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgentSkill(BaseModel):
    """A2A v1.0 AgentSkill — one thing an agent can do.

    ``id`` is the stable machine handle; ``name`` is the human label.
    ``subject`` is the future NATS routing address (None until W2 wires
    routing).  camelCase aliases let ``to_a2a_json()`` emit spec-compliant JSON.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    input_modes: list[str] = Field(default_factory=list, alias="inputModes")
    output_modes: list[str] = Field(default_factory=list, alias="outputModes")
    # Kernel extension: transport address — None until W2
    subject: str | None = None

    @model_validator(mode="after")
    def _non_empty_id(self) -> AgentSkill:
        if not self.id.strip():
            raise ValueError("skill id must be non-empty")
        return self


class AgentCapabilities(BaseModel):
    """A2A v1.0 capabilities block — protocol feature flags."""

    model_config = ConfigDict(populate_by_name=True)

    streaming: bool = False
    push_notifications: bool = Field(False, alias="pushNotifications")
    state_transition_history: bool = Field(False, alias="stateTransitionHistory")


class AgentCard(BaseModel):
    """An agent's declarative self-description — the payload of a discovery reply.

    Shaped to the A2A v1.0 spec (a2a-protocol.org).  Kernel extensions
    (``activatable``, ``tools``, per-skill ``subject``) are defined fields, not
    extra JSON — they survive round-trips through ``model_dump()`` /
    ``model_validate()``.  ``to_a2a_json()`` emits spec-compliant camelCase JSON.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    # A2A v1.0 required
    name: str
    description: str = ""
    url: str = ""
    version: str = "0"
    protocol_version: str = Field("1.0", alias="protocolVersion")

    # A2A v1.0 optional
    provider: dict[str, str] | None = None
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)  # type: ignore[arg-type]
    default_input_modes: list[str] = Field(default_factory=lambda: ["application/json"], alias="defaultInputModes")
    default_output_modes: list[str] = Field(default_factory=lambda: ["application/json"], alias="defaultOutputModes")
    skills: list[AgentSkill] = Field(default_factory=list)
    security_schemes: dict[str, Any] | None = Field(None, alias="securitySchemes")
    security: list[dict[str, list[str]]] | None = None

    # Kernel extensions
    tools: list[str] = Field(default_factory=list)
    activatable: bool = False

    @model_validator(mode="after")
    def _validate(self) -> AgentCard:
        if not self.name.strip():
            raise ValueError("agent name must be non-empty")
        ids = [s.id for s in self.skills]
        if len(ids) != len(set(ids)):
            raise ValueError("skill ids must be unique within an agent card")
        return self

    def skill_ids(self) -> list[str]:
        return [s.id for s in self.skills]

    def has_skill(self, skill_id: str) -> bool:
        return any(s.id == skill_id for s in self.skills)

    def skill(self, skill_id: str) -> AgentSkill | None:
        """Return the skill with the given id, or None."""
        for s in self.skills:
            if s.id == skill_id:
                return s
        return None

    def to_a2a_json(self) -> dict[str, Any]:
        """Spec-compliant camelCase dict suitable for ``/.well-known/agent.json``."""
        return self.model_dump(by_alias=True, exclude_none=True)
