"""session subcommands — list, status."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from agentix_cli._config import load_config
from agentix_cli._output import error, make_table, print_kv, print_table

app = typer.Typer(help="Inspect sessions stored in the SQLite kernel database.")


def _require_db(cfg_path: Path | None) -> Path:
    cfg = load_config(cfg_path)
    if not cfg.sqlite_path:
        error("sqlite_path not set in config. Add 'sqlite_path: ~/.agentix/kernel.db' to your config file.")
        raise typer.Exit(1)
    if not cfg.sqlite_path.exists():
        error(f"Database not found: {cfg.sqlite_path}")
        raise typer.Exit(1)
    return cfg.sqlite_path


async def _query(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.command("list")
def session_list(
    limit: int = typer.Option(20, help="Max number of sessions to show"),
    status: str | None = typer.Option(None, help="Filter by status (running, completed, failed, paused)"),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """List recent sessions from the SQLite kernel database."""
    db = _require_db(config_path)

    sql = "SELECT id, customer_id, status, started_at, ended_at, total_cost_usd, total_input_tokens, total_output_tokens FROM sessions"
    args: tuple = ()
    if status:
        sql += " WHERE status = ?"
        args = (status,)
    sql += " ORDER BY started_at DESC LIMIT ?"
    args = (*args, limit)

    rows = asyncio.run(_query(db, sql, args))
    if not rows:
        typer.echo("No sessions found.")
        return

    t = make_table("ID", "Customer", "Status", "Started", "Ended", "Cost (€)", "In tok", "Out tok")
    for r in rows:
        cost = f"{r['total_cost_usd']:.4f}" if r["total_cost_usd"] else "0.0000"
        ended = r["ended_at"][:19] if r["ended_at"] else "—"
        status_style = {
            "running": "[cyan]running[/cyan]",
            "completed": "[green]completed[/green]",
            "failed": "[red]failed[/red]",
            "paused": "[yellow]paused[/yellow]",
        }.get(r["status"], r["status"])
        t.add_row(
            r["id"][:16] + "…",
            r["customer_id"],
            status_style,
            r["started_at"][:19],
            ended,
            cost,
            str(r["total_input_tokens"]),
            str(r["total_output_tokens"]),
        )
    print_table(t)


@app.command("status")
def session_status(
    session_id: str = typer.Argument(..., help="Session ID (or prefix)"),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Show detailed status for a single session."""
    db = _require_db(config_path)

    rows = asyncio.run(_query(db, "SELECT * FROM sessions WHERE id LIKE ? LIMIT 1", (f"{session_id}%",)))
    if not rows:
        error(f"Session not found: {session_id!r}")
        raise typer.Exit(1)

    s = rows[0]
    print_kv(
        [
            ("ID", s["id"]),
            ("Customer", s["customer_id"]),
            ("Status", s["status"]),
            ("Started", s["started_at"]),
            ("Ended", s["ended_at"] or "—"),
            ("Cost (€)", f"{s['total_cost_usd']:.6f}"),
            ("Input tokens", s["total_input_tokens"]),
            ("Output tokens", s["total_output_tokens"]),
            ("Intervention", s.get("intervention_type", "—")),
            ("Outcome", s.get("outcome") or "—"),
            ("Control-plane ID", s.get("control_plane_id") or "—"),
            ("Parent session", s.get("parent_session_id") or "—"),
            ("Lease expires", s.get("lease_expires_at") or "—"),
        ],
        title=f"Session {s['id'][:20]}",
    )

    # Turns summary
    turns = asyncio.run(
        _query(
            db,
            "SELECT turn_index, role, tool_name, input_tokens, output_tokens, cost_usd, latency_ms FROM turns WHERE session_id = ? ORDER BY turn_index",
            (s["id"],),
        )
    )
    if turns:
        typer.echo("")
        t = make_table("#", "Role", "Tool", "In tok", "Out tok", "Cost (€)", "ms", title="Turns")
        for tr in turns:
            t.add_row(
                str(tr["turn_index"]),
                tr["role"],
                tr["tool_name"] or "—",
                str(tr["input_tokens"]),
                str(tr["output_tokens"]),
                f"{tr['cost_usd']:.4f}",
                str(tr["latency_ms"] or "—"),
            )
        print_table(t)
