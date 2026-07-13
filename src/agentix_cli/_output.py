"""Rich output helpers — tables, panels, status indicators."""

from __future__ import annotations

from typing import Any

from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def make_table(*columns: str, title: str | None = None) -> Table:
    t = Table(title=title, show_header=True, header_style="bold cyan", border_style="dim")
    for col in columns:
        t.add_column(col)
    return t


def print_table(table: Table) -> None:
    console.print(table)


def print_panel(content: str, title: str = "", style: str = "blue") -> None:
    console.print(Panel(content, title=title, border_style=style))


def print_kv(pairs: list[tuple[str, Any]], title: str = "") -> None:
    t = make_table("Key", "Value", title=title or None)
    for k, v in pairs:
        t.add_row(str(k), str(v) if v is not None else "[dim]—[/dim]")
    print_table(t)


def ok(msg: str) -> None:
    rprint(f"[green]✓[/green] {msg}")


def warn(msg: str) -> None:
    rprint(f"[yellow]![/yellow] {msg}")


def error(msg: str) -> None:
    err_console.print(f"[red]✗[/red] {msg}")


def dry_run_header() -> None:
    rprint("[bold yellow]── DRY RUN — no changes will be made ──[/bold yellow]")


def would(msg: str) -> None:
    rprint(f"[yellow]  would:[/yellow] {msg}")
