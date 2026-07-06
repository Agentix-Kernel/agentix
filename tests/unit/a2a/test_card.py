"""AgentCard + Capability — A2A discovery data model (euroblaze/ludo #492, W2 seed)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentix.a2a import AgentCard, Capability


def test_card_construction_and_lookups() -> None:
    card = AgentCard(
        name="concierge",
        description="lifecycle agent",
        version="1",
        capabilities=[
            Capability(name="notify", description="send a nudge"),
            Capability(name="schedule", subject="int.ops.acct.schedule"),
        ],
        tools=["send_email", "schedule_job"],
        activatable=True,
    )
    assert card.capability_names() == ["notify", "schedule"]
    assert card.has_capability("notify")
    assert not card.has_capability("missing")
    assert card.capability("schedule").subject == "int.ops.acct.schedule"  # type: ignore[union-attr]
    assert card.capability("missing") is None


def test_defaults() -> None:
    card = AgentCard(name="minimal")
    assert card.capabilities == []
    assert card.tools == []
    assert card.activatable is False
    assert card.version == "0"


def test_empty_agent_name_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentCard(name="   ")


def test_empty_capability_name_rejected() -> None:
    with pytest.raises(ValidationError):
        Capability(name="")


def test_duplicate_capability_names_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentCard(
            name="a",
            capabilities=[Capability(name="dup"), Capability(name="dup")],
        )


def test_round_trip_serialization() -> None:
    card = AgentCard(name="ops", capabilities=[Capability(name="read")], tools=["grep"])
    dumped = card.model_dump()
    restored = AgentCard.model_validate(dumped)
    assert restored == card


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        AgentCard.model_validate({"name": "x", "creds": "secret"})
