"""Agent app skeleton generator."""

from __future__ import annotations

from agentixd.scaffold.driver_tpl import _to_class_name, _to_module


def render_agent(name: str, description: str = "") -> list[dict[str, str]]:
    """Return list of {path, content} dicts for a new agent app skeleton."""
    mod = _to_module(name)
    cls = _to_class_name(name).replace("Driver", "")
    desc = description or f"{name} agent built on agentix"

    files: list[dict[str, str]] = []

    def _add(path: str, content: str) -> None:
        files.append({"path": f"{mod}/{path}", "content": content})

    _add("__init__.py", f'"""{desc}"""\n')

    _add(
        "config.py",
        f'''\
"""KernelConfig subclass for {name}."""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

from agentix.config import KernelConfig


@dataclass(frozen=True)
class {cls}Config(KernelConfig):
    """Extend with {name}-specific config fields here."""
    pass
''',
    )

    _add(
        "main.py",
        f'''\
"""Entry point for {name} — submits work to agentixd via agentix_sdk."""

from __future__ import annotations

import asyncio

from agentix_sdk import AgentixClient


async def main() -> None:
    async with AgentixClient() as client:
        if not await client.is_ready():
            raise RuntimeError("agentixd is not running — start it with: agentixd")

        session = await client.create_session(customer_id="{mod}-default")
        print(f"Session {{session.id}} created")

        turn = await client.run_turn(session.id, message="Hello from {name}")
        print(f"Turn status: {{turn.status}}")


if __name__ == "__main__":
    asyncio.run(main())
''',
    )

    _add("tools/__init__.py", "")

    _add(
        "tools/example_tool.py",
        f'''\
"""Example tool for {name}."""

from __future__ import annotations

from pydantic import BaseModel

from agentix.tools.base import Tool, ToolContext


class ExampleInput(BaseModel):
    text: str


class ExampleOutput(BaseModel):
    result: str


class ExampleTool(Tool):
    name = "example_tool"
    description = "An example tool — replace with real implementation."
    input_schema = ExampleInput
    output_schema = ExampleOutput
    mutates_target = False
    verifier: str | None = None

    async def __call__(self, args: ExampleInput, ctx: ToolContext) -> ExampleOutput:
        return ExampleOutput(result=f"processed: {{args.text}}")
''',
    )

    _add(
        "skills/example/SKILL.md",
        f"""\
# Example Skill

This is a starter skill for {name}.

## Steps

1. Identify the task.
2. Use the available tools.
3. Return a clear result.
""",
    )

    _add(
        "skills/example/manifest.yaml",
        f"""\
name: example
description: Starter skill for {name}
tools: []
""",
    )

    _add("tests/__init__.py", "")

    _add(
        "tests/test_example.py",
        f'''\
"""Smoke tests for {name} — run via API against a live agentixd."""

from __future__ import annotations

import pytest
from agentix_sdk import AgentixClient


@pytest.mark.integration
async def test_create_session() -> None:
    async with AgentixClient() as client:
        assert await client.is_ready(), "agentixd must be running for integration tests"
        session = await client.create_session(customer_id="{mod}-test")
        assert session.id
        assert session.status == "running"
''',
    )

    return files
