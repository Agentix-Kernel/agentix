"""Provider-selection helpers — the single source of truth for activation."""

from __future__ import annotations

from pathlib import Path

from agentix.config import (
    AnthropicConfig,
    HubleConfig,
    KernelConfig,
    MeliousConfig,
    anthropic_active,
    enabled_providers,
    select_enabled_provider,
)
from agentix.storage import MinioConfig


def _cfg(**providers: object) -> KernelConfig:
    return KernelConfig(
        config_path=Path("/tmp/cfg.yaml"),
        minio=MinioConfig(endpoint="localhost:0", access_key="x", secret_key="x"),
        sqlite_path=Path("/tmp/db.sqlite"),
        memory_path=Path("/tmp/memory"),
        **providers,  # type: ignore[arg-type]
    )


def test_anthropic_active_requires_a_credential() -> None:
    assert anthropic_active(AnthropicConfig()) is False
    assert anthropic_active(AnthropicConfig(api_key="sk-ant-x")) is True
    assert anthropic_active(AnthropicConfig(keychain_service="Claude Code-credentials")) is True


def test_enabled_providers_priority_order() -> None:
    cfg = _cfg(
        melious=MeliousConfig(enabled=True),
        huble=HubleConfig(enabled=True),
        anthropic=AnthropicConfig(api_key="sk-ant-x"),
    )
    assert [name for name, _ in enabled_providers(cfg)] == ["melious", "huble", "anthropic"]


def test_enabled_providers_skips_inactive() -> None:
    cfg = _cfg(huble=HubleConfig(enabled=True))
    assert [name for name, _ in enabled_providers(cfg)] == ["huble"]


def test_select_primary_is_first_by_priority() -> None:
    cfg = _cfg(huble=HubleConfig(enabled=True), anthropic=AnthropicConfig(api_key="k"))
    name, pc = select_enabled_provider(cfg)
    assert name == "huble"
    assert isinstance(pc, HubleConfig)


def test_select_falls_back_to_anthropic_when_nothing_active() -> None:
    cfg = _cfg()  # no provider configured
    assert enabled_providers(cfg) == []
    name, pc = select_enabled_provider(cfg)
    assert name == "anthropic"
    assert isinstance(pc, AnthropicConfig)
