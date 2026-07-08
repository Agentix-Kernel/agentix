"""OAuth billing-header resolution — env-override first, then default."""

from __future__ import annotations

import pytest

from agentix.drivers.adapters.anthropic import _DEFAULT_BILLING_HEADER, _billing_header


def test_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTIX_ANTHROPIC_BILLING_HEADER", raising=False)
    assert _billing_header() == _DEFAULT_BILLING_HEADER


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTIX_ANTHROPIC_BILLING_HEADER", "override")
    assert _billing_header() == "override"


def test_empty_override_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTIX_ANTHROPIC_BILLING_HEADER", "")
    assert _billing_header() == _DEFAULT_BILLING_HEADER
