"""A2A (agent-to-agent) — the discovery data model.

This package is the **first, safe slice** of the A2A epic (euroblaze/ludo #492):
the declarative ``AgentCard`` + ``Capability`` types an agent publishes to
describe itself, plus validation. It carries **no** transport, credentials, or
trust-zone isolation — the security-sensitive substrate (NATS trust-zone
Accounts, credential minting, the capability subject-space, ActionGate) is
deliberately deferred to W1-W3 and lands only with its own review.

An ``AgentCard`` is what a peer receives on discovery (the future NATS micro
``INFO`` reply): enough to decide *whether* and *what* to delegate, with the
actual routing/authz added on top later.
"""

from agentix.a2a.card import AgentCard, Capability

__all__ = ["AgentCard", "Capability"]
