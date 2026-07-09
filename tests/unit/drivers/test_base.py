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


def test_descriptor_minimal_model_type() -> None:
    d = DriverDescriptor(name="anthropic", type="model", modality="chat")
    assert d.source == "api"
    assert d.pricing_ref is None
    assert d.capabilities == frozenset()


def test_descriptor_rejects_empty_name_and_type() -> None:
    with pytest.raises(ValueError, match="name"):
        DriverDescriptor(name="", type="model", modality="chat")
    with pytest.raises(ValueError, match="type"):
        DriverDescriptor(name="x", type="")


def test_descriptor_model_type_requires_modality() -> None:
    with pytest.raises(ValueError, match="modality"):
        DriverDescriptor(name="x", type="model")


def test_descriptor_non_model_type_allows_no_modality() -> None:
    # The open-vocabulary promise: a database driver needs no kernel change.
    d = DriverDescriptor(name="mysql-main", type="database", source="local")
    assert d.modality is None


def test_descriptor_is_frozen_and_hashable() -> None:
    d = DriverDescriptor(name="a", type="model", modality="stt", capabilities=frozenset({"streaming"}))
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


# ───────────────────── base protocol ─────────────────────


class _FakeDbDriver:
    """Proof the base protocol carries no model assumptions."""

    def __init__(self) -> None:
        self._descriptor = DriverDescriptor(name="fake-db", type="database", source="local")
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
