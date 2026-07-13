"""AgentCard + AgentSkill + AgentCapabilities — A2A v1.0 data model tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentix.a2a import AgentCapabilities, AgentCard, AgentSkill

# ── AgentCard construction ────────────────────────────────────────────────────


def test_card_construction_and_skill_lookups() -> None:
    card = AgentCard(
        name="concierge",
        description="lifecycle agent",
        version="1",
        skills=[
            AgentSkill(id="notify", name="Notify", description="send a nudge"),
            AgentSkill(
                id="schedule",
                name="Schedule",
                subject="int.ops.acct.schedule",
                tags=["ops"],
                inputModes=["application/json"],
                outputModes=["application/json"],
            ),
        ],
        tools=["send_email", "schedule_job"],
        activatable=True,
    )
    assert card.skill_ids() == ["notify", "schedule"]
    assert card.has_skill("notify")
    assert not card.has_skill("missing")
    assert card.skill("schedule").subject == "int.ops.acct.schedule"  # type: ignore[union-attr]
    assert card.skill("missing") is None


def test_defaults() -> None:
    card = AgentCard(name="minimal")
    assert card.skills == []
    assert card.tools == []
    assert card.activatable is False
    assert card.version == "0"
    assert card.protocol_version == "1.0"
    assert isinstance(card.capabilities, AgentCapabilities)
    assert card.capabilities.streaming is False


def test_empty_agent_name_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentCard(name="   ")


def test_empty_skill_id_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentSkill(id="", name="bad")


def test_duplicate_skill_ids_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentCard(
            name="a",
            skills=[AgentSkill(id="dup", name="dup"), AgentSkill(id="dup", name="dup2")],
        )


def test_round_trip_serialization() -> None:
    card = AgentCard(
        name="ops",
        skills=[AgentSkill(id="read", name="Read", tags=["io"])],
        tools=["grep"],
    )
    dumped = card.model_dump()
    restored = AgentCard.model_validate(dumped)
    assert restored == card


def test_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        AgentCard.model_validate({"name": "x", "creds": "secret"})


# ── to_a2a_json camelCase round-trip ─────────────────────────────────────────


def test_to_a2a_json_camel_case() -> None:
    card = AgentCard(
        name="bot",
        skills=[
            AgentSkill(
                id="analyse",
                name="Analyse",
                inputModes=["application/json"],
                outputModes=["text/plain"],
                tags=["schema"],
            )
        ],
        capabilities=AgentCapabilities(streaming=True, pushNotifications=False),
    )
    j = card.to_a2a_json()
    assert j["name"] == "bot"
    assert j["protocolVersion"] == "1.0"
    # capabilities block uses camelCase
    assert "pushNotifications" in j["capabilities"]
    assert j["capabilities"]["streaming"] is True
    # skills use camelCase for inputModes / outputModes
    skill_j = j["skills"][0]
    assert skill_j["id"] == "analyse"
    assert "inputModes" in skill_j
    assert skill_j["inputModes"] == ["application/json"]
    assert skill_j["outputModes"] == ["text/plain"]
    # None fields excluded
    assert "provider" not in j
    assert "securitySchemes" not in j


def test_to_a2a_json_round_trip() -> None:
    """model_validate(to_a2a_json()) must reproduce the same card."""
    card = AgentCard(
        name="rt",
        url="https://10.0.99.1/agents/rt",
        skills=[AgentSkill(id="s1", name="S1", tags=["t"])],
    )
    j = card.to_a2a_json()
    restored = AgentCard.model_validate(j)
    assert restored == card


# ── AgentCapabilities ─────────────────────────────────────────────────────────


def test_agent_capabilities_defaults() -> None:
    caps = AgentCapabilities()
    assert caps.streaming is False
    assert caps.push_notifications is False
    assert caps.state_transition_history is False


def test_agent_capabilities_camel_alias() -> None:
    caps = AgentCapabilities(pushNotifications=True, stateTransitionHistory=True)
    assert caps.push_notifications is True
    assert caps.state_transition_history is True
    j = caps.model_dump(by_alias=True)
    assert j["pushNotifications"] is True
    assert j["stateTransitionHistory"] is True
