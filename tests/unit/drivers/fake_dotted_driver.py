"""Fixture module for the dotted-path driver-construction test."""

from __future__ import annotations

from agentix.drivers.base import DriverDescriptor


class FakeDottedDriver:
    """Follows the seam-#13 dotted-path constructor contract."""

    def __init__(self, *, spec: object, api_key: str | None) -> None:
        self.spec = spec
        self.api_key = api_key
        self._descriptor = DriverDescriptor(name="dotted", type="database", source="local")

    @property
    def descriptor(self) -> DriverDescriptor:
        return self._descriptor

    async def aclose(self) -> None:
        pass


class FakeLeasedDriver:
    """Follows the leased dotted-path contract (seam-#13 lease path)."""

    def __init__(self, *, spec: object, api_key: str | None, credentials: object) -> None:
        self.spec = spec
        self.api_key = api_key
        self.credentials = credentials
        self.closed = False
        name = str(getattr(spec, "name", "leased"))
        self._descriptor = DriverDescriptor(name=name, type="erp-fake", source="local")

    @property
    def descriptor(self) -> DriverDescriptor:
        return self._descriptor

    async def aclose(self) -> None:
        self.closed = True
