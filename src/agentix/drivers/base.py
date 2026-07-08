"""Driver core — the kernel's first-class abstraction for external-system I/O.

A *driver* is a modular, developer-programmable unit of I/O against an
external system. The first family is AI models of any modality (chat,
embedding, vision, tts, stt, timeseries) from any source (provider API,
gateway, huggingface, local runtime), but the base contract is deliberately
system-agnostic: a future database or queue driver registers through the
same descriptor + lifecycle + error taxonomy without any kernel change.

This module is the import root of ``agentix.drivers`` — it imports nothing
from the rest of the package (per-kind families build on top of it, never
the other way round).

Canonical doc: ``docs/drivers.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

# ─────────────────────────── descriptor ───────────────────────────

#: Modality vocabulary for ``kind="model"`` drivers. Free-form ``str`` on the
#: descriptor so apps can extend; these are the values the kernel documents.
KNOWN_MODALITIES = ("chat", "embedding", "vision", "tts", "stt", "timeseries")

#: Source vocabulary — where the model/system actually runs.
KNOWN_SOURCES = ("api", "gateway", "huggingface", "local")


@dataclass(frozen=True)
class DriverDescriptor:
    """Identity + metadata a registry entry resolves to.

    ``kind`` selects the protocol family (the verb set a driver speaks):
    ``"model"`` today; ``"database"``, ``"queue"``, … later — an open
    vocabulary, no kernel enum to amend. ``modality`` refines model-kind
    drivers (chat/embedding/stt/…) and is ``None`` for non-model kinds.
    """

    name: str
    kind: str = "model"
    modality: str | None = None
    source: str = "api"
    capabilities: frozenset[str] = field(default_factory=frozenset)
    default_model: str | None = None
    #: Key into the operator pricing table (``KernelConfig.llm_pricing``).
    #: ``None`` = this driver's spend is not token-priced / not recorded.
    pricing_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("DriverDescriptor.name must be non-empty")
        if not self.kind:
            raise ValueError("DriverDescriptor.kind must be non-empty")
        if self.kind == "model" and not self.modality:
            raise ValueError("DriverDescriptor: kind='model' requires a modality")


# ─────────────────────────── error taxonomy ───────────────────────────


class DriverError(Exception):
    """Base class for driver errors.

    ``retryable`` is the single classification the failover chain reads:
    classification happens once, in the adapter; everyone upstream just
    branches on the flag.
    """

    def __init__(self, message: str, *, driver: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.driver = driver
        self.retryable = retryable


class DriverRateLimited(DriverError):
    """The external system signalled a rate limit. Always retryable."""

    def __init__(self, message: str, *, driver: str) -> None:
        super().__init__(message, driver=driver, retryable=True)


class DriverUnavailable(DriverError):
    """The external system is temporarily unreachable (5xx, timeout). Retryable."""

    def __init__(self, message: str, *, driver: str) -> None:
        super().__init__(message, driver=driver, retryable=True)


class DriverInvalidRequest(DriverError):
    """The request itself is malformed — do not retry the same payload."""

    def __init__(self, message: str, *, driver: str) -> None:
        super().__init__(message, driver=driver, retryable=False)


# ─────────────────────────── base protocol ───────────────────────────


@runtime_checkable
class Driver(Protocol):
    """The universal driver surface: identity + lifecycle, no I/O verbs.

    Per-kind protocols (``ChatDriver``, ``EmbeddingDriver``, ``SttDriver``,
    a future ``DatabaseDriver``) extend this with their typed verbs — the
    kernel deliberately ships no generic ``infer(Any) -> Any``: it would
    erase the typing mypy enforces and force isinstance dances on callers.
    """

    @property
    def descriptor(self) -> DriverDescriptor: ...

    async def aclose(self) -> None:
        """Release underlying resources (HTTP clients, connections)."""
        ...
