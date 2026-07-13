"""scaffold subcommands — driver and agent skeleton generation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from agentix_cli._output import dry_run_header, ok, would

app = typer.Typer(help="Generate driver stubs and agent app skeletons.")


async def _try_scaffold_driver(name: str, modality: str, description: str = "") -> dict | None:
    """Attempt scaffold via agentixd UDS. Returns None if daemon is unreachable."""
    try:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as client:
            f = await client.scaffold_driver(name=name, modality=modality, description=description)
            return {"path": f.path, "content": f.content}
    except Exception:
        return None


async def _try_scaffold_agent(name: str, description: str) -> list | None:
    """Attempt scaffold via agentixd UDS. Returns None if daemon is unreachable."""
    try:
        from agentix_sdk import AgentixClient

        async with AgentixClient() as client:
            files = await client.scaffold_agent(name=name, description=description)
            return [{"path": f.path, "content": f.content} for f in files]
    except Exception:
        return None


@app.command("driver")
def scaffold_driver(
    name: str = typer.Argument(..., help="Driver name (e.g. my_llm, my-provider)"),
    modality: str = typer.Option("chat", help="Driver modality: chat, embedding, stt"),
    output: Path = typer.Option(Path("."), "--output", "-o", help="Output directory"),
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Preview without writing")] = False,
) -> None:
    """Generate a driver stub .py file."""
    result = asyncio.run(_try_scaffold_driver(name, modality))

    if result is None:
        # Local generation (no daemon needed — templates are bundled)
        from agentixd.scaffold.driver_tpl import render_driver

        try:
            filename, content = render_driver(name, modality)
        except ValueError as exc:
            from agentix_cli._output import error

            error(str(exc))
            raise typer.Exit(1) from None
        result = {"path": filename, "content": content}

    dest = output / result["path"]

    if dry_run:
        dry_run_header()
        would(f"write {dest} ({len(result['content'])} bytes)")
        typer.echo("\n--- preview (first 20 lines) ---")
        for line in result["content"].splitlines()[:20]:
            typer.echo(f"  {line}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result["content"])
    ok(f"Driver stub written: {dest}")
    typer.echo(f"\nNext: implement {dest.stem}.complete() and register the driver factory.")


@app.command("agent")
def scaffold_agent(
    name: str = typer.Argument(..., help="Agent/app name (e.g. my_agent)"),
    description: str = typer.Option("", "--description", "-d", help="One-line description"),
    output: Path = typer.Option(Path("."), "--output", "-o", help="Output directory (creates <name>/ inside)"),
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Preview without writing")] = False,
) -> None:
    """Generate an agent app skeleton directory."""
    files = asyncio.run(_try_scaffold_agent(name, description))

    if files is None:
        from agentixd.scaffold.agent_tpl import render_agent

        files = render_agent(name, description)

    if dry_run:
        dry_run_header()
        for f in files:
            would(f"write {output / f['path']}")
        return

    for f in files:
        dest = output / f["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f["content"])

    ok(f"Agent skeleton written: {output / name.replace('-', '_')}/")
    typer.echo(f"\n{len(files)} files created. Start with: {output / name.replace('-', '_')}/main.py")
