"""Session-scoped credential leases (seam #13 lease path, agentix#80).

Covers: scope="session" specs are never built at startup; registry.lease()
hands out per-credential instances invisible to name lookup; lease lifetime
via the context manager; the session_scope / aclose_all leak backstops; and
the two construction contracts (dotted path with credentials kwarg,
register_credentialed_factory).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from agentix.config import DriverSpec, KernelConfig
from agentix.drivers.base import Driver
from agentix.drivers.factory import build_drivers, register_credentialed_factory
from agentix.drivers.registry import DriverConflict, DriverRegistry
from agentix.drivers.session import session_scope
from agentix.storage import MinioConfig
from tests.unit.drivers.fake_dotted_driver import FakeLeasedDriver

_DOTTED = "tests.unit.drivers.fake_dotted_driver:FakeLeasedDriver"


def _cfg(*specs: DriverSpec) -> KernelConfig:
    return KernelConfig(
        config_path=Path("/tmp/cfg.yaml"),
        minio=MinioConfig(endpoint="localhost:0", access_key="x", secret_key="x"),
        sqlite_path=Path("/tmp/db.sqlite"),
        memory_path=Path("/tmp/memory"),
        drivers=specs,
    )


def _session_spec(name: str = "erp-target") -> DriverSpec:
    return DriverSpec(name=name, driver=_DOTTED, type="erp-fake", modality="other", scope="session")


def _leased(driver: Driver) -> FakeLeasedDriver:
    return cast(FakeLeasedDriver, driver)


# ── build_drivers routing ─────────────────────────────────────────


def test_session_spec_not_built_at_startup() -> None:
    registry = build_drivers(_cfg(_session_spec()))
    assert registry.leasable_names() == ["erp-target"]
    assert len(registry) == 0
    with pytest.raises(KeyError):
        registry.get("erp-target")


def test_session_spec_unknown_factory_key_fails_loud() -> None:
    spec = DriverSpec(name="bad", driver="no-such-key", scope="session")
    with pytest.raises(ValueError, match="credentialed"):
        build_drivers(_cfg(spec))


# ── lease lifetime + isolation ────────────────────────────────────


@pytest.mark.asyncio
async def test_lease_yields_fresh_credentialed_instances() -> None:
    registry = build_drivers(_cfg(_session_spec()))
    async with (
        registry.lease("erp-target", {"login": "a"}) as one,
        registry.lease("erp-target", {"login": "b"}) as two,
    ):
        assert one is not two
        assert _leased(one).credentials == {"login": "a"}
        assert _leased(two).credentials == {"login": "b"}
        # Leased instances never enter the name table.
        assert "erp-target" not in registry
        assert len(registry) == 0
    assert _leased(one).closed and _leased(two).closed


@pytest.mark.asyncio
async def test_lease_unknown_name_raises() -> None:
    registry = DriverRegistry()
    with pytest.raises(KeyError, match="leasable"):
        registry.lease("nope", {})


def test_leasable_name_conflicts_with_instances() -> None:
    registry = build_drivers(_cfg(_session_spec("dup")))
    with pytest.raises(DriverConflict):
        registry.register_leasable("dup", lambda creds: None)  # type: ignore[arg-type,return-value]


# ── teardown backstops ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_session_scope_drains_leaked_leases_per_session() -> None:
    registry = build_drivers(_cfg(_session_spec()))
    leaked: dict[str, Any] = {}

    async with session_scope("s-other", registry=registry):
        other_lease = registry.lease("erp-target", {"login": "other"})
        leaked["other"] = await other_lease.__aenter__()

        async with session_scope("s-1", registry=registry):
            lease = registry.lease("erp-target", {"login": "one"})
            leaked["one"] = await lease.__aenter__()
            # deliberately no __aexit__ — the scope must drain it

        # s-1's leak is closed; s-other's lease (still in scope) is not.
        assert _leased(leaked["one"]).closed
        assert not _leased(leaked["other"]).closed
    assert _leased(leaked["other"]).closed


@pytest.mark.asyncio
async def test_aclose_all_drains_outstanding_leases() -> None:
    registry = build_drivers(_cfg(_session_spec()))
    lease = registry.lease("erp-target", {"login": "x"})
    driver = await lease.__aenter__()
    await registry.aclose_all()
    assert _leased(driver).closed


# ── construction contracts ────────────────────────────────────────


@pytest.mark.asyncio
async def test_registered_credentialed_factory_path() -> None:
    def _factory(spec: DriverSpec, cfg: KernelConfig, credentials: Any) -> Driver:
        return FakeLeasedDriver(spec=spec, api_key=None, credentials=credentials)  # type: ignore[return-value]

    register_credentialed_factory("erp-fake-keyed", _factory)
    try:
        spec = DriverSpec(name="keyed", driver="erp-fake-keyed", type="erp-fake", modality="other", scope="session")
        registry = build_drivers(_cfg(spec))
        async with registry.lease("keyed", {"db": "prod"}) as driver:
            assert _leased(driver).credentials == {"db": "prod"}
    finally:
        from agentix.drivers import factory as factory_mod

        factory_mod._CREDENTIALED_FACTORIES.pop("erp-fake-keyed", None)


def test_register_credentialed_factory_conflict() -> None:
    from agentix.drivers import factory as factory_mod

    register_credentialed_factory("erp-fake-dup", lambda s, c, creds: None)  # type: ignore[arg-type,return-value]
    try:
        with pytest.raises(ValueError, match="already registered"):
            register_credentialed_factory("erp-fake-dup", lambda s, c, creds: None)  # type: ignore[arg-type,return-value]
    finally:
        factory_mod._CREDENTIALED_FACTORIES.pop("erp-fake-dup", None)
