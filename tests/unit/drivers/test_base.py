"""Unit tests for the driver core — descriptor, protocol, error taxonomy."""

from __future__ import annotations

import pytest

from agentix.drivers import (
    Driver,
    DriverDescriptor,
    DriverError,
    DriverInvalidRequest,
    DriverRateLimited,
    DriverUnavailable,
)

# ───────────────────── descriptor ─────────────────────


def test_descriptor_minimal_model_kind() -> None:
    d = DriverDescriptor(name="anthropic", kind="model", modality="chat")
    assert d.source == "api"
    assert d.pricing_ref is None
    assert d.capabilities == frozenset()


def test_descriptor_rejects_empty_name_and_kind() -> None:
    with pytest.raises(ValueError, match="name"):
        DriverDescriptor(name="", kind="model", modality="chat")
    with pytest.raises(ValueError, match="kind"):
        DriverDescriptor(name="x", kind="")


def test_descriptor_model_kind_requires_modality() -> None:
    with pytest.raises(ValueError, match="modality"):
        DriverDescriptor(name="x", kind="model")


def test_descriptor_non_model_kind_allows_no_modality() -> None:
    # The open-vocabulary promise: a database driver needs no kernel change.
    d = DriverDescriptor(name="mysql-main", kind="database", source="local")
    assert d.modality is None


def test_descriptor_is_frozen_and_hashable() -> None:
    d = DriverDescriptor(name="a", kind="model", modality="stt", capabilities=frozenset({"streaming"}))
    with pytest.raises(AttributeError):
        d.name = "b"  # type: ignore[misc]
    assert hash(d)


# ───────────────────── error taxonomy ─────────────────────


@pytest.mark.parametrize(
    ("exc_cls", "retryable"),
    [
        (DriverRateLimited, True),
        (DriverUnavailable, True),
        (DriverInvalidRequest, False),
    ],
)
def test_taxonomy_retryability_matrix(exc_cls: type[DriverError], retryable: bool) -> None:
    err = exc_cls("boom", driver="d1")
    assert isinstance(err, DriverError)
    assert err.driver == "d1"
    assert err.retryable is retryable


def test_base_error_defaults_to_not_retryable() -> None:
    assert DriverError("x", driver="d").retryable is False


# ───────────────────── LlmError re-base (until 0.5.0 final) ─────────────────────


def test_llm_errors_are_driver_errors() -> None:
    from agentix.llm.base import LlmError, LlmInvalidRequest, LlmRateLimit, LlmUnavailable

    for cls, retryable in ((LlmRateLimit, True), (LlmUnavailable, True), (LlmInvalidRequest, False)):
        err = cls("boom", provider="p1")
        assert isinstance(err, DriverError)
        assert err.retryable is retryable
        # provider is a read-only alias of driver during the migration window.
        assert err.provider == "p1"
        assert err.driver == "p1"
        assert err.provider == err.driver

    generic = LlmError("x", provider="p2", retryable=True)
    assert isinstance(generic, DriverError)
    assert generic.retryable is True


# ───────────────────── base protocol ─────────────────────


class _FakeDbDriver:
    """Proof the base protocol carries no model assumptions."""

    def __init__(self) -> None:
        self._descriptor = DriverDescriptor(name="fake-db", kind="database", source="local")
        self.closed = False

    @property
    def descriptor(self) -> DriverDescriptor:
        return self._descriptor

    async def aclose(self) -> None:
        self.closed = True


def test_protocol_structural_conformance() -> None:
    fake = _FakeDbDriver()
    assert isinstance(fake, Driver)


@pytest.mark.asyncio
async def test_protocol_lifecycle() -> None:
    fake = _FakeDbDriver()
    await fake.aclose()
    assert fake.closed is True
