"""Shared agent-card persistence — read/write ~/.agentix/agents.json.

Used by both agentix_cli and agentixd routes so that fixes (locking,
schema migration) only need to be applied in one place.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def agents_file(config_path: Path) -> Path:
    """Return the agents.json path adjacent to the given config file."""
    return config_path.parent / "agents.json"


def load_agents(agents_file: Path) -> list[dict[str, Any]]:
    """Load the agent-card list from disk; return [] on missing or corrupt file."""
    if not agents_file.exists():
        return []
    try:
        return list(json.loads(agents_file.read_text()))  # type: ignore[no-any-return]
    except (json.JSONDecodeError, OSError):
        return []


def save_agents(agents_file: Path, agents: list[dict[str, Any]]) -> None:
    """Persist the agent-card list atomically (write then rename not needed here;
    agents.json is local-only and small)."""
    agents_file.parent.mkdir(parents=True, exist_ok=True)
    agents_file.write_text(json.dumps(agents, indent=2))
