"""context subcommands — show."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

from agentix_cli._config import load_config
from agentix_cli._output import error, make_table, print_kv, print_table

app = typer.Typer(help="Show context window usage for a session.")


async def _query(db_path: Path, sql: str, params: tuple = ()) -> list[dict]:
    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
    return [dict(r) for r in rows]


@app.command("show")
def context_show(
    session_id: str | None = typer.Option(
        None, "--session", "-s", help="Session ID (or prefix). Defaults to the most recent session."
    ),
    config_path: Path | None = typer.Option(None, "--config"),
) -> None:
    """Show context window usage — token budget breakdown per turn."""
    cfg = load_config(config_path)
    if not cfg.sqlite_path or not cfg.sqlite_path.exists():
        error("sqlite_path not configured or database not found. Set sqlite_path in your config.")
        raise typer.Exit(1)

    db = cfg.sqlite_path

    # Resolve session
    if session_id:
        sessions = asyncio.run(_query(db, "SELECT * FROM sessions WHERE id LIKE ? LIMIT 1", (f"{session_id}%",)))
    else:
        sessions = asyncio.run(_query(db, "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 1"))

    if not sessions:
        error("No session found.")
        raise typer.Exit(1)

    s = sessions[0]
    turns = asyncio.run(
        _query(
            db,
            "SELECT turn_index, role, tool_name, input_tokens, output_tokens, cost_usd, latency_ms, created_at FROM turns WHERE session_id = ? ORDER BY turn_index",
            (s["id"],),
        )
    )

    total_in = sum(t["input_tokens"] for t in turns)
    total_out = sum(t["output_tokens"] for t in turns)
    total_cost = sum(t["cost_usd"] for t in turns)
    turn_count = len(turns)

    print_kv(
        [
            ("Session ID", s["id"]),
            ("Status", s["status"]),
            ("Total turns", turn_count),
            ("Total input tokens", f"{total_in:,}"),
            ("Total output tokens", f"{total_out:,}"),
            ("Total tokens", f"{total_in + total_out:,}"),
            ("Total cost (€)", f"{total_cost:.6f}"),
            ("Budget (€)", f"{cfg.budget_usd:.2f}"),
            ("Budget remaining (€)", f"{cfg.budget_usd - total_cost:.6f}"),
        ],
        title=f"Context — Session {s['id'][:20]}",
    )

    if turns:
        typer.echo("")
        t = make_table("#", "Role", "Tool", "In tok", "Out tok", "Cumul in", "Cumul out", title="Token usage per turn")
        cumul_in = cumul_out = 0
        for tr in turns:
            cumul_in += tr["input_tokens"]
            cumul_out += tr["output_tokens"]
            t.add_row(
                str(tr["turn_index"]),
                tr["role"],
                tr["tool_name"] or "—",
                str(tr["input_tokens"]),
                str(tr["output_tokens"]),
                f"{cumul_in:,}",
                f"{cumul_out:,}",
            )
        print_table(t)
