"""NATS request/reply subjects for agent introspection (read-only, internal-only).

Hand-written (not generated). Vendored byte-identical to ludo-gateway and ludo-webapps.
All subjects are under the ``ludo.agent.introspect.*`` namespace so they are easy to ACL.
Request payloads and responses are JSON-encoded bytes.
"""

INTROSPECT_HEALTHZ = "ludo.agent.introspect.healthz"
INTROSPECT_ESCALATIONS = "ludo.agent.introspect.escalations"
INTROSPECT_BLUEPRINTS = "ludo.agent.introspect.blueprints"
INTROSPECT_BLUEPRINTS_GET = "ludo.agent.introspect.blueprints.get"
INTROSPECT_MEMORY_CATALOGUE = "ludo.agent.introspect.memory.catalogue"
INTROSPECT_MEMORY_RENAMES = "ludo.agent.introspect.memory.renames"
INTROSPECT_MEMORY_STATS = "ludo.agent.introspect.memory.stats"
INTROSPECT_MEMORY_TRAJECTORIES_SEARCH = "ludo.agent.introspect.memory.trajectories.search"
INTROSPECT_MEMORY_ADVISE = "ludo.agent.introspect.memory.advise"

__all__ = [
    "INTROSPECT_HEALTHZ",
    "INTROSPECT_ESCALATIONS",
    "INTROSPECT_BLUEPRINTS",
    "INTROSPECT_BLUEPRINTS_GET",
    "INTROSPECT_MEMORY_CATALOGUE",
    "INTROSPECT_MEMORY_RENAMES",
    "INTROSPECT_MEMORY_STATS",
    "INTROSPECT_MEMORY_TRAJECTORIES_SEARCH",
    "INTROSPECT_MEMORY_ADVISE",
]
