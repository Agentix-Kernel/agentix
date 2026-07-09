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
