"""Unit tests for the ``model_override`` wiring through
``build_llm_provider``. Lets operators swap the HUBLE/Melious upstream
model per-run (e.g. a CLI ``--model`` flag) without editing config —
required for model-bench workflows that compare N candidate models on
the same scenario.

The override changes ONLY the HUBLE/Melious provider's model. The
Anthropic fallback model stays as configured (operator-set, not
typically swapped per-run).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from agentix.runtime import build_llm_provider


def _fake_huble_cfg() -> Any:
    cfg = MagicMock()
    cfg.melious.enabled = False
    cfg.huble.enabled = True
    cfg.huble.base_url = "https://huble.example/api"
    cfg.huble.api_key = "fake-key"
    cfg.huble.upstream_provider = "melious"
    cfg.huble.model = "glm-4.7"  # config default
    cfg.anthropic.api_key = None
    cfg.anthropic.oauth_credentials_path = None
    cfg.anthropic.keychain_service = None
    cfg.anthropic.model = "claude-haiku-4-5"
    return cfg


def test_build_llm_provider_uses_config_model_when_no_override() -> None:
    """No override → HUBLE provider built with cfg.huble.model."""
    cfg = _fake_huble_cfg()
    captured: dict[str, Any] = {}

    class _FakeHuble:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    with patch("agentix.llm.huble.HubleProvider", _FakeHuble):
        build_llm_provider(cfg)

    assert captured.get("model") == "glm-4.7"
    assert captured.get("upstream_provider") == "melious"


def test_build_llm_provider_applies_model_override_to_huble() -> None:
    """``model_override`` swaps HUBLE provider's model for this build
    only — config is untouched (caller's cfg object preserved)."""
    cfg = _fake_huble_cfg()
    original = cfg.huble.model
    captured: dict[str, Any] = {}

    class _FakeHuble:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    with patch("agentix.llm.huble.HubleProvider", _FakeHuble):
        build_llm_provider(cfg, model_override="qwen3-next-80b-a3b-thinking")

    assert captured.get("model") == "qwen3-next-80b-a3b-thinking"
    # cfg untouched.
    assert cfg.huble.model == original


def test_build_llm_provider_none_override_falls_through_to_config() -> None:
    """An unset override is passed as None (the strip()-or-None idiom
    in CLI handlers) — must NOT clobber the config model."""
    cfg = _fake_huble_cfg()
    captured: dict[str, Any] = {}

    class _FakeHuble:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    with patch("agentix.llm.huble.HubleProvider", _FakeHuble):
        build_llm_provider(cfg, model_override=None)

    assert captured.get("model") == "glm-4.7"


def test_build_llm_provider_override_does_not_affect_anthropic_fallback() -> None:
    """When both HUBLE and Anthropic are configured, the override
    swaps the HUBLE model only — Anthropic fallback model is
    untouched (operator typically wants a stable fallback target,
    not one that swaps with the bench parameter)."""
    cfg = _fake_huble_cfg()
    cfg.anthropic.api_key = "anthro-fake"

    huble_captured: dict[str, Any] = {}
    anthro_captured: dict[str, Any] = {}

    class _FakeHuble:
        def __init__(self, **kwargs: Any) -> None:
            huble_captured.update(kwargs)

    class _FakeAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            anthro_captured.update(kwargs)

    with (
        patch("agentix.llm.huble.HubleProvider", _FakeHuble),
        patch("agentix.llm.AnthropicProvider", _FakeAnthropic),
    ):
        build_llm_provider(cfg, model_override="hermes-4-405b")

    assert huble_captured.get("model") == "hermes-4-405b"
    # Anthropic fallback model unchanged.
    assert anthro_captured.get("model") == "claude-haiku-4-5"
