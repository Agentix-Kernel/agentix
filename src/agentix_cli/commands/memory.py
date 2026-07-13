"""memory subcommands — list, show."""

from __future__ import annotations

from pathlib import Path

import typer

from agentix_cli._config import load_config
from agentix_cli._output import error, make_table, print_table, warn

app = typer.Typer(help="Inspect memory pages and working memory.")


def _require_memory(config_path: Path | None) -> Path:
    cfg = load_config(config_path)
    if not cfg.memory_path:
        error("memory_path not set in config. Add 'memory_path: ~/.agentix/memory' to your config.")
        raise typer.Exit(1)
    return cfg.memory_path


@app.command("list")
def memory_list(
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """List all memory pages in the memory store."""
    mem_path = _require_memory(config_path)
    if not mem_path.exists():
        warn(f"Memory path does not exist: {mem_path}")
        return

    pages = sorted(mem_path.rglob("*.md"))
    if not pages:
        typer.echo("No memory pages found.")
        return

    t = make_table("Page", "Size", "Modified")
    for p in pages:
        stat = p.stat()
        rel = p.relative_to(mem_path)
        size = f"{stat.st_size:,} B"
        import datetime

        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
        t.add_row(str(rel), size, mtime)
    print_table(t)
    typer.echo(f"\n{len(pages)} page(s) in {mem_path}")


@app.command("show")
def memory_show(
    page: str | None = typer.Argument(
        None, help="Page filename (e.g. 'customer-acme.md'). Shows all pages if omitted."
    ),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Show content of a memory page (or list sections if no page given)."""
    mem_path = _require_memory(config_path)
    if not mem_path.exists():
        warn(f"Memory path does not exist: {mem_path}")
        return

    if page:
        target = mem_path / page
        if not target.exists():
            # Try partial match
            matches = list(mem_path.rglob(f"*{page}*"))
            if not matches:
                error(f"Memory page not found: {page}")
                raise typer.Exit(1)
            target = matches[0]
        typer.echo(target.read_text())
    else:
        # Show a summary: page name + H2 section headings
        pages = sorted(mem_path.rglob("*.md"))
        if not pages:
            typer.echo("No memory pages found.")
            return
        import re

        _H2 = re.compile(r"^##\s+(.+)$", re.MULTILINE)
        for p in pages:
            rel = p.relative_to(mem_path)
            content = p.read_text(errors="replace")
            sections = _H2.findall(content)
            sec_str = ", ".join(sections[:5]) if sections else "—"
            typer.echo(f"[bold]{rel}[/bold]  sections: {sec_str}")
