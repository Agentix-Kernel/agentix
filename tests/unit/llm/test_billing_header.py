"""OAuth billing-header resolution + legacy-env deprecation warning."""

from __future__ import annotations

import pytest
from structlog.testing import capture_logs

import agentix.llm.anthropic as anthropic_mod
from agentix.llm.anthropic import _DEFAULT_BILLING_HEADER, _billing_header


@pytest.fixture(autouse=True)
def _reset_warn_flag() -> None:
    # The one-time warning latch is module-global; reset around each test.
    anthropic_mod._legacy_billing_warned = False


def test_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTIX_ANTHROPIC_BILLING_HEADER", raising=False)
    monkeypatch.delenv("LUDO_ANTHROPIC_BILLING_HEADER", raising=False)
    assert _billing_header() == _DEFAULT_BILLING_HEADER


def test_new_env_wins_over_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTIX_ANTHROPIC_BILLING_HEADER", "new")
    monkeypatch.setenv("LUDO_ANTHROPIC_BILLING_HEADER", "legacy")
    assert _billing_header() == "new"


def test_legacy_env_used_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTIX_ANTHROPIC_BILLING_HEADER", raising=False)
    monkeypatch.setenv("LUDO_ANTHROPIC_BILLING_HEADER", "legacy")
    with capture_logs() as logs:
        assert _billing_header() == "legacy"
        assert _billing_header() == "legacy"  # second call: no second warning
    warnings = [e for e in logs if e.get("event") == "anthropic.billing_header.legacy_env"]
    assert len(warnings) == 1
    assert warnings[0]["use_instead"] == "AGENTIX_ANTHROPIC_BILLING_HEADER"
