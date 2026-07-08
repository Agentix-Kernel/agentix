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

__all__ = [
    "KNOWN_MODALITIES",
    "KNOWN_SOURCES",
    "Driver",
    "DriverDescriptor",
    "DriverError",
    "DriverInvalidRequest",
    "DriverRateLimited",
    "DriverUnavailable",
]
