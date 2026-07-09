"""Driver registry — the runtime container of built driver instances.

House style mirrors ``agentix.tools.registry.ToolRegistry``: strict
``register`` for kernel-built instances (failure is a bug), lenient
``try_register`` for app extension loops (one broken third-party driver
must not down the process). Lookup is by unique ``descriptor.name``;
typed accessors (``chat()``/``embedding()``/``stt()``) resolve the
declared default instance per modality.

Default resolution is a **pure lookup — explicitly not routing policy**:
registration order (first-in per modality) or an explicit
``default=True`` at registration decides; there is no scoring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog

from agentix.drivers.base import Driver, DriverDescriptor

if TYPE_CHECKING:
    from agentix.drivers.chat import ChatDriver
    from agentix.drivers.embedding import EmbeddingDriver
    from agentix.drivers.object_store import ObjectStoreDriver
    from agentix.drivers.relational import RelationalDriver
    from agentix.drivers.speech import SttDriver

log = structlog.get_logger(__name__)

__all__ = ["DriverConflict", "DriverRegistry"]


class DriverConflict(Exception):
    """A driver with the same descriptor.name is already registered."""


class DriverRegistry:
    """Holds built driver instances, keyed by unique ``descriptor.name``."""

    def __init__(self) -> None:
        self._drivers: dict[str, Driver] = {}
        # (type, modality-or-None) -> default driver name.
        self._defaults: dict[tuple[str, str | None], str] = {}

    # ── registration ──────────────────────────────────────────────

    def register(self, driver: Driver, *, default: bool = False) -> None:
        """Strict registration — raises on conflict. Kernel-built instances
        use this: a name collision or a descriptor-less object is a bug."""
        desc = getattr(driver, "descriptor", None)
        if not isinstance(desc, DriverDescriptor):
            raise TypeError(f"register: {driver!r} carries no DriverDescriptor (not a Driver)")
        if desc.name in self._drivers:
            raise DriverConflict(f"driver {desc.name!r} already registered")
        self._drivers[desc.name] = driver
        slot = (desc.type, desc.modality)
        if default or slot not in self._defaults:
            self._defaults[slot] = desc.name

    def try_register(self, driver: Driver, *, default: bool = False) -> bool:
        """Lenient registration — log + skip on failure, keep going.
        For app extension loops (config-declared third-party drivers)."""
        try:
            self.register(driver, default=default)
        except (DriverConflict, TypeError) as exc:
            log.warning("driver_registry.skip", error=str(exc)[:200])
            return False
        return True

    # ── lookup ────────────────────────────────────────────────────

    def get(self, name: str) -> Driver:
        """Return the driver registered under ``name``; raises KeyError."""
        if name not in self._drivers:
            raise KeyError(f"no driver registered under {name!r}")
        return self._drivers[name]

    def _default_for(self, type: str, modality: str | None, name: str | None) -> Driver:
        if name is not None:
            return self.get(name)
        default_name = self._defaults.get((type, modality))
        if default_name is None:
            raise KeyError(f"no {type}/{modality} driver registered")
        return self._drivers[default_name]

    def chat(self, name: str | None = None) -> ChatDriver:
        """The default (or named) chat driver — pure lookup, not policy."""
        driver = self._default_for("model", "chat", name)
        if not hasattr(driver, "complete"):
            raise TypeError(f"driver {driver.descriptor.name!r} is not a ChatDriver")
        return cast("ChatDriver", driver)

    def embedding(self, name: str | None = None) -> EmbeddingDriver:
        """The default (or named) embedding driver; raises when absent."""
        driver = self._default_for("model", "embedding", name)
        if not hasattr(driver, "embed"):
            raise TypeError(f"driver {driver.descriptor.name!r} is not an EmbeddingDriver")
        return cast("EmbeddingDriver", driver)

    def stt(self, name: str | None = None) -> SttDriver:
        """The default (or named) speech-to-text driver; raises when absent."""
        driver = self._default_for("model", "stt", name)
        if not hasattr(driver, "transcribe"):
            raise TypeError(f"driver {driver.descriptor.name!r} is not an SttDriver")
        return cast("SttDriver", driver)

    def relational(self, name: str | None = None) -> RelationalDriver:
        """The default (or named) relational driver; raises when absent."""
        driver = self._default_for("storage", "relational", name)
        if not hasattr(driver, "query_one"):
            raise TypeError(f"driver {driver.descriptor.name!r} is not a RelationalDriver")
        return cast("RelationalDriver", driver)

    def object_store(self, name: str | None = None) -> ObjectStoreDriver:
        """The default (or named) object-store driver; raises when absent."""
        driver = self._default_for("storage", "object", name)
        if not hasattr(driver, "put_bytes"):
            raise TypeError(f"driver {driver.descriptor.name!r} is not an ObjectStoreDriver")
        return cast("ObjectStoreDriver", driver)

    def object_store_or_none(self, name: str | None = None) -> ObjectStoreDriver | None:
        """Like :meth:`object_store` but None when no backend is declared."""
        try:
            return self.object_store(name)
        except KeyError:
            return None

    def embedding_or_none(self, name: str | None = None) -> EmbeddingDriver | None:
        """Like :meth:`embedding` but None when no backend is configured —
        callers thread None into ToolContext.embeddings and downstream code
        falls back to the lexical baseline."""
        try:
            return self.embedding(name)
        except KeyError:
            return None

    def by_type(self, type: str) -> list[Driver]:
        return [d for d in self._drivers.values() if d.descriptor.type == type]

    def by_modality(self, modality: str) -> list[Driver]:
        return [d for d in self._drivers.values() if d.descriptor.modality == modality]

    def types(self) -> list[str]:
        return sorted({d.descriptor.type for d in self._drivers.values()})

    def all_drivers(self) -> list[Driver]:
        """Every registered driver, sorted by (type, modality, name)."""
        return sorted(
            self._drivers.values(),
            key=lambda d: (d.descriptor.type, d.descriptor.modality or "", d.descriptor.name),
        )

    def descriptors(self) -> list[DriverDescriptor]:
        return [d.descriptor for d in self.all_drivers()]

    def __contains__(self, name: str) -> bool:
        return name in self._drivers

    def __len__(self) -> int:
        return len(self._drivers)

    # ── lifecycle ─────────────────────────────────────────────────

    async def aclose_all(self) -> None:
        """Close every registered driver. Exceptions are logged, never
        raised — shutdown must complete."""
        for name, driver in self._drivers.items():
            try:
                await driver.aclose()
            except Exception as exc:  # pragma: no cover — best-effort close
                log.warning("driver_registry.close_failed", driver=name, error=str(exc)[:200])
