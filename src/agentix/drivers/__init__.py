"""agentix.drivers — the kernel's abstraction for external-system I/O.

Public surface grows per phase of the v0.5 re-founding; import from here,
not from submodules. Canonical doc: ``docs/drivers.md``.
"""

from agentix.drivers.base import (
    KNOWN_MODALITIES,
    KNOWN_SOURCES,
    Driver,
    DriverDescriptor,
    DriverError,
    DriverInvalidRequest,
    DriverRateLimited,
    DriverUnavailable,
)
from agentix.drivers.chat import (
    ChatDriver,
    ChatRequest,
    ChatResponse,
    ToolSpec,
    tool_to_spec,
)

__all__ = [
    "KNOWN_MODALITIES",
    "KNOWN_SOURCES",
    "ChatDriver",
    "ChatRequest",
    "ChatResponse",
    "Driver",
    "DriverDescriptor",
    "DriverError",
    "DriverInvalidRequest",
    "DriverRateLimited",
    "DriverUnavailable",
    "ToolSpec",
    "tool_to_spec",
]
