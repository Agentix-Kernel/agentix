"""A2A (agent-to-agent) — discovery data model.

First, safe slice of the A2A epic (euroblaze/ludo #492): the A2A v1.0-shaped
``AgentCard`` + ``AgentSkill`` + ``AgentCapabilities`` types an agent publishes
to describe itself, plus validation.  No transport, credentials or trust-zone
isolation — security-sensitive substrate lands in W1–W3.
"""

from agentix.a2a.card import AgentCapabilities, AgentCard, AgentSkill

__all__ = ["AgentCard", "AgentSkill", "AgentCapabilities"]
