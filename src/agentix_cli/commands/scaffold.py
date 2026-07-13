"""scaffold subcommands — driver and agent skeleton generation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from agentix_cli._output import dry_run_header, ok, would

app = typer.Typer(help="Generate driver stubs and agent app skeletons.")


def _daemon_url() -> str | None:
    """Return the running daemon URL, or None if daemon is not up."""
    import httpx

    from agentix_cli._config import load_config

    cfg = load_config()
    host = "10.0.99.1"
    port = 7320
    if cfg._raw:
        d = cfg._raw.get("daemon", {})
        host = d.get("host", host)
        port = int(d.get("port", port))
    url = f"http://{host}:{port}"
    try:
        r = httpx.get(f"{url}/health/live", timeout=1.5)
        return url if r.status_code == 200 else None
    except Exception:
        return None


async def _scaffold_driver_via_daemon(url: str, name: str, modality: str) -> dict:
    import httpx

    async with httpx.AsyncClient(base_url=url, timeout=10.0) as client:
        r = await client.post("/admin/scaffold/driver", json={"name": name, "modality": modality})
        r.raise_for_status()
        return r.json()


async def _scaffold_agent_via_daemon(url: str, name: str, description: str) -> list:
    import httpx

    async with httpx.AsyncClient(base_url=url, timeout=10.0) as client:
        r = await client.post("/admin/scaffold/agent", json={"name": name, "description": description})
        r.raise_for_status()
        return r.json()


@app.command("driver")
def scaffold_driver(
    name: str = typer.Argument(..., help="Driver name (e.g. my_llm, my-provider)"),
    modality: str = typer.Option("chat", help="Driver modality: chat, embedding, stt"),
    output: Path = typer.Option(Path("."), "--output", "-o", help="Output directory"),
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Preview without writing")] = False,
) -> None:
    """Generate a driver stub .py file."""
    daemon = _daemon_url()

    if daemon:
        try:
            result = asyncio.run(_scaffold_driver_via_daemon(daemon, name, modality))
        except Exception as exc:
            from agentix_cli._output import error

            error(f"daemon call failed: {exc} — falling back to local generation")
            daemon = None

    if not daemon:
        # Local generation (no daemon needed — templates are bundled)
        from agentixd.scaffold.driver_tpl import render_driver

        try:
            filename, content = render_driver(name, modality)
        except ValueError as exc:
            from agentix_cli._output import error

            error(str(exc))
            raise typer.Exit(1) from None
        result = {"filename": filename, "content": content}

    filename = result["filename"]
    content = result["content"]
    dest = output / filename

    if dry_run:
        dry_run_header()
        would(f"write {dest} ({len(content)} bytes)")
        typer.echo("\n--- preview (first 20 lines) ---")
        for line in content.splitlines()[:20]:
            typer.echo(f"  {line}")
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
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
    daemon = _daemon_url()

    if daemon:
        try:
            files = asyncio.run(_scaffold_agent_via_daemon(daemon, name, description))
        except Exception as exc:
            from agentix_cli._output import error

            error(f"daemon call failed: {exc} — falling back to local generation")
            daemon = None

    if not daemon:
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
