"""agent subcommands — list, register, unregister.

Agent cards (A2A self-descriptions) are stored in ~/.agentix/agents.json.
When agentixd is running, commands route through its admin API so the daemon
is the single source of truth. Falls back to direct file access when no
daemon socket is found.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Any

import typer

from agentix.a2a import agents_file as _agents_file_for
from agentix.a2a import load_agents, save_agents
from agentix_cli._config import load_config
from agentix_cli._output import dry_run_header, error, make_table, ok, print_kv, print_table, would

app = typer.Typer(help="Manage A2A agent cards (list, register, unregister).")

_DEFAULT_SOCKET = Path.home() / ".agentix" / "agentixd.sock"


async def _sdk_list() -> list[dict[str, Any]] | None:
    """Return agent list from agentixd, or None if daemon not available."""
    if not _DEFAULT_SOCKET.exists():
        return None
    try:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as c:
            cards = await c.list_agents()
            return [card.model_dump() for card in cards]
    except Exception:
        return None


async def _sdk_register(card_data: dict[str, Any], dry_run: bool) -> dict[str, Any] | None:
    if not _DEFAULT_SOCKET.exists():
        return None
    try:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as c:
            return await c.register_agent(card_data, dry_run=dry_run)
    except Exception:
        return None


async def _sdk_unregister(name: str, dry_run: bool) -> dict[str, Any] | None:
    if not _DEFAULT_SOCKET.exists():
        return None
    try:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as c:
            return await c.unregister_agent(name, dry_run=dry_run)
    except Exception:
        return None


def _agents_file(config_path: Path | None) -> Path:
    cfg = load_config(config_path)
    return _agents_file_for(cfg.config_path)


@app.command("list")
def agent_list(
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """List registered A2A agent cards."""
    agents = asyncio.run(_sdk_list())
    if agents is None:
        af = _agents_file(config_path)
        agents = load_agents(af)
    if not agents:
        typer.echo("No agents registered. Use 'agentix agent register <name>'.")
        return

    t = make_table("Name", "Version", "Activatable", "Capabilities", "Description")
    for a in agents:
        caps = ", ".join(s["name"] for s in a.get("skills", []))
        activatable = "[yellow]yes[/yellow]" if a.get("activatable") else "no"
        t.add_row(a.get("name", "—"), a.get("version", "0"), activatable, caps or "—", a.get("description", "—")[:60])
    print_table(t)
    typer.echo(f"\n{len(agents)} agent(s) in {af}")


@app.command("register")
def agent_register(
    name: str = typer.Argument(..., help="Agent name"),
    description: str = typer.Option("", help="Agent description"),
    version: str = typer.Option("0", help="Agent version"),
    activatable: bool = typer.Option(False, help="Mark as key-gated activatable agent"),
    capabilities: str | None = typer.Option(None, "--capabilities", "-c", help="Comma-separated capability names"),
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Preview without applying")] = False,
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Register a new A2A agent card."""
    from agentix.a2a.card import AgentCard, AgentSkill

    skills_list = (
        [AgentSkill(id=c.strip(), name=c.strip()) for c in capabilities.split(",") if c.strip()] if capabilities else []
    )

    try:
        card = AgentCard(
            name=name, description=description, version=version, activatable=activatable, skills=skills_list
        )
    except Exception as exc:
        error(f"Invalid agent card: {exc}")
        raise typer.Exit(1) from None

    if dry_run:
        dry_run_header()
        would(f"register agent card {name!r} (v{version})")
        would(f"capabilities: {[c.name for c in skills_list] or '(none)'}")
        return

    result = asyncio.run(_sdk_register(card.model_dump(), dry_run=False))
    if result is not None:
        ok(f"Agent {name!r} registered via agentixd")
        return
    # fallback: file
    af = _agents_file(config_path)
    agents = load_agents(af)
    agents = [a for a in agents if a.get("name") != name]
    agents.append(card.model_dump())
    save_agents(af, agents)
    ok(f"Agent {name!r} registered in {af}")


@app.command("unregister")
def agent_unregister(
    name: str = typer.Argument(..., help="Agent name to remove"),
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Preview without applying")] = False,
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Remove an A2A agent card."""
    af = _agents_file(config_path)
    agents = load_agents(af)
    match = next((a for a in agents if a.get("name") == name), None)

    if dry_run:
        dry_run_header()
        would(f"remove agent card {name!r}")
        return

    result = asyncio.run(_sdk_unregister(name, dry_run=False))
    if result is not None:
        ok(f"Agent {name!r} removed via agentixd")
        return
    # fallback: file
    if match is None:
        error(f"Agent {name!r} not found.")
        raise typer.Exit(1)
    agents = [a for a in agents if a.get("name") != name]
    save_agents(af, agents)
    ok(f"Agent {name!r} removed from {af}")


@app.command("show")
def agent_show(
    name: str = typer.Argument(..., help="Agent name"),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Show details for a registered agent card."""
    af = _agents_file(config_path)
    agents = load_agents(af)
    match = next((a for a in agents if a.get("name") == name), None)
    if match is None:
        error(f"Agent {name!r} not found.")
        raise typer.Exit(1)

    skills = match.get("skills", [])
    print_kv(
        [
            ("Name", match.get("name")),
            ("Description", match.get("description") or "—"),
            ("Version", match.get("version", "0")),
            ("Activatable", "yes" if match.get("activatable") else "no"),
            ("Tools", ", ".join(match.get("tools", [])) or "—"),
            ("Skills", ", ".join(s["name"] for s in skills) if skills else "—"),
        ],
        title=f"Agent: {name}",
    )
