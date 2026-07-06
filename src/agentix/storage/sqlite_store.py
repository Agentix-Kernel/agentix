"""Operational state in SQLite (WAL + FTS5) — the kernel store.

Holds everything *operational* — sessions, per-turn traces, safety events,
errors — behind a relational schema the dashboard and resumability code
depend on. This is the **app-agnostic** base: the ``sessions`` row carries only
generic fields (id, ``customer_id``, status, token/cost totals, checkpoint) plus
an ``app_meta`` JSON blob the app fills with its own scope (e.g. the migration
app's source/target version + target models). Apps subclass this store to add
their own tables (see ``ludo.storage.ludo_sqlite.LudoSqliteStore`` which adds the
``diagnoses`` + ``applied_memory_rules`` tables and their queries).

``safety_events.kind`` is an open string. The kernel emits a few generic kinds
(``dry_run_block``, ``per_batch_verify_fail``, …); apps pass their own kinds
(e.g. the migration app's ``xmlid_rollback``) as plain strings.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import aiosqlite
import structlog

log = structlog.get_logger(__name__)

SessionStatus = Literal["running", "paused", "completed", "failed"]
TurnRole = Literal["user", "assistant", "tool"]
# Per-session human-touchpoint classification — the autonomy product
# metric. ``none`` is the goal: a clean run with zero operator involvement.
# Every other value is one human touchpoint the autonomous loop did not close.
InterventionType = Literal["none", "aborted", "novel", "stuck", "partial"]
# ``safety_events.kind`` is an open string (app-extensible). These are the
# generic kinds the kernel SafetyGate emits; apps add their own.
SafetyKind = str
KERNEL_SAFETY_KINDS: frozenset[str] = frozenset(
    {
        "dry_run_block",
        "pre_flight_abort",
        "per_batch_verify_fail",
        "session_end_verify_fail",
        "memory_lock_timeout",
        "provider_failover",  # ProviderRouter fell over to a fallback
    }
)

# Current live schema version — bump when a migration adds or alters a
# table, and append a migration block in ``_apply_migrations``.
# Databases with no schema_version row get initialised to
# _SCHEMA_VERSION: they are already at the latest shape because
# CREATE TABLE IF NOT EXISTS took care of it.
#
# v12 = the kernel/app split: the Odoo columns
# (source_version/target_version/target_models) collapse into the generic
# ``app_meta`` JSON, and the ``diagnoses`` + ``applied_memory_rules`` tables
# move to the app subclass (``ludo.storage.ludo_sqlite``). ``customer_id`` is
# kept as the generic opaque tenant id. App-owned historical steps
# (v3/v7/v9/v10/v11) run in ``_migrate_app``.
_SCHEMA_VERSION = 12

_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        customer_id TEXT NOT NULL,
        status TEXT NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        total_input_tokens INTEGER NOT NULL DEFAULT 0,
        total_output_tokens INTEGER NOT NULL DEFAULT 0,
        total_cost_usd REAL NOT NULL DEFAULT 0.0,
        checkpoint TEXT,
        -- App-specific session scope as a JSON object. The kernel treats it
        -- opaquely; apps read their own keys. '{}' = no app scope
        -- (auto-discovery / spike / probe). NOT NULL with a default so the
        -- column read is always safe.
        app_meta TEXT NOT NULL DEFAULT '{}',
        -- Human-touchpoint classification for this session — the autonomy
        -- product metric. Counts of non-'none' values per account show whether
        -- the autonomous loop is converging. Written at session close.
        intervention_type TEXT NOT NULL DEFAULT 'none',
        -- Honest session outcome label, derived from session-end verification
        -- rather than the agent's terminal message. NULL until computed at
        -- session close; rows that predate it stay NULL (unjudged).
        outcome TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_sessions_customer ON sessions (customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions (status)",
    """
    CREATE TABLE IF NOT EXISTS turns (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        turn_index INTEGER NOT NULL,
        role TEXT NOT NULL,
        content_ref TEXT,
        content_inline TEXT,
        tool_name TEXT,
        tool_ok INTEGER,
        latency_ms INTEGER,
        input_tokens INTEGER NOT NULL DEFAULT 0,
        output_tokens INTEGER NOT NULL DEFAULT 0,
        cost_usd REAL NOT NULL DEFAULT 0.0,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_turns_session ON turns (session_id, turn_index)",
    """
    CREATE TABLE IF NOT EXISTS safety_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        turn_id INTEGER REFERENCES turns(id) ON DELETE SET NULL,
        tool_name TEXT,
        tool_input TEXT,
        kind TEXT NOT NULL,
        detail TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_safety_events_session ON safety_events (session_id, kind)",
    """
    CREATE TABLE IF NOT EXISTS errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        turn_id INTEGER REFERENCES turns(id) ON DELETE SET NULL,
        model TEXT,
        external_id TEXT,
        error_class TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_errors_session ON errors (session_id)",
    # Target-health log — populated by the `omg migrate` pre-flight
    # ping. A circuit breaker reads back the most recent rows per URL
    # to decide whether to let a new session start.
    """
    CREATE TABLE IF NOT EXISTS target_health (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        ok INTEGER NOT NULL,
        error_class TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_target_health_url_time ON target_health (url, created_at)",
    # v9: tool progress events. Tools call ctx.progress(...) to write
    # rows for in-flight visibility. percent is 0.0..1.0 or NULL.
    """
    CREATE TABLE IF NOT EXISTS tool_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        tool_name TEXT NOT NULL,
        percent REAL,
        message TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tool_progress_session ON tool_progress (session_id, created_at)",
    # FTS5 virtual table mirroring the searchable columns on `turns`. Kept in
    # sync via AFTER INSERT / UPDATE / DELETE triggers below.
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
        session_id,
        tool_name,
        content_inline,
        content='turns',
        content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
        INSERT INTO turns_fts (rowid, session_id, tool_name, content_inline)
        VALUES (new.id, new.session_id, COALESCE(new.tool_name, ''), COALESCE(new.content_inline, ''));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
        INSERT INTO turns_fts (turns_fts, rowid, session_id, tool_name, content_inline)
        VALUES ('delete', old.id, old.session_id, COALESCE(old.tool_name, ''), COALESCE(old.content_inline, ''));
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS turns_au AFTER UPDATE ON turns BEGIN
        INSERT INTO turns_fts (turns_fts, rowid, session_id, tool_name, content_inline)
        VALUES ('delete', old.id, old.session_id, COALESCE(old.tool_name, ''), COALESCE(old.content_inline, ''));
        INSERT INTO turns_fts (rowid, session_id, tool_name, content_inline)
        VALUES (new.id, new.session_id, COALESCE(new.tool_name, ''), COALESCE(new.content_inline, ''));
    END
    """,
)


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


class SqliteStore:
    """Async operational-state store backed by a single SQLite file.

    Opens the database on ``initialize()``, enables WAL + a busy timeout +
    foreign keys, and runs the schema DDL idempotently. Keeps a single
    long-lived connection; ``aiosqlite`` serialises individual statements on
    its worker thread.

    Concurrency: the worker is single-flight (one run at a time), so there is
    no concurrent access to serialise and **no in-process lock**. A logical
    ``execute``+``commit`` is therefore atomic only under that single-writer
    discipline — running sessions concurrently in one process (``gather``)
    would need a per-task connection or a transaction lock, because
    ``commit()`` flushes *all* pending writes on the shared connection
    (agentix#39 / isolation.md I2, deferred). Cross-process safety (a 2nd
    worker on the same WAL file) is covered by ``busy_timeout``: a concurrent
    writer waits rather than failing immediately with ``SQLITE_BUSY``.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._db: aiosqlite.Connection | None = None

    # ─────────────────────────────── lifecycle ─────────────────────────────

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA foreign_keys=ON")
        # A concurrent writer (e.g. a 2nd worker process on the same WAL file)
        # waits up to 30s for the lock instead of failing immediately with
        # SQLITE_BUSY. Explicit + higher than the implicit sqlite3 5s
        # connect-timeout default (agentix#39 / isolation.md I2).
        await self._db.execute("PRAGMA busy_timeout=30000")
        # Base (kernel) DDL first, then any app-specific tables the subclass adds.
        for stmt in (*_SCHEMA_STATEMENTS, *self._extra_schema_statements()):
            await self._db.execute(stmt)
        await self._apply_migrations()
        await self._db.commit()
        log.info("sqlite.initialized", path=str(self.path), schema_version=_SCHEMA_VERSION)

    def _extra_schema_statements(self) -> tuple[str, ...]:
        """App-specific CREATE TABLE / INDEX DDL. Base kernel adds none.

        Apps override to append their own tables (e.g. the migration app's
        ``diagnoses`` + ``applied_memory_rules``). Runs right after the kernel
        DDL, before migrations."""
        return ()

    async def _migrate_app(self, current: int) -> None:
        """App-specific migration steps for an existing DB. Base is a no-op.

        Runs inside ``_apply_migrations`` after the generic session-column
        migrations, before the ``schema_version`` bump. ``current`` is the
        DB's schema version before this run. Apps override to migrate their
        own tables (guard every step by column/table existence so it is a
        safe no-op on a fresh DB)."""
        return

    async def _apply_migrations(self) -> None:
        """Bump ``schema_version`` and apply any pending migrations.

        Migrations run in order, inside the same transaction as
        ``initialize()``. ``CREATE TABLE IF NOT EXISTS`` above defines
        the shape for FRESH databases; this block ALTERs existing tables.
        Every step is guarded by column/table existence so it no-ops on a
        fresh DB (which starts at ``current`` 0 and still runs the blocks).
        """
        assert self._db is not None
        async with self._db.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version") as cur:
            row = await cur.fetchone()
        current = int(row[0]) if row else 0
        if current >= _SCHEMA_VERSION:
            return

        # v5 → v6: sessions.intervention_type — the human-touchpoint metric.
        if current < 6:
            existing = await self._session_columns()
            if "intervention_type" not in existing:
                await self._db.execute("ALTER TABLE sessions ADD COLUMN intervention_type TEXT NOT NULL DEFAULT 'none'")

        # v6 → v7: sessions.outcome — the honest session-end outcome label.
        if current < 7:
            existing = await self._session_columns()
            if "outcome" not in existing:
                await self._db.execute("ALTER TABLE sessions ADD COLUMN outcome TEXT")

        # v11 → v12: the kernel/app split. Add the generic ``app_meta`` column;
        # the app backfills it from the legacy source_version/target_version/
        # target_models columns in ``_migrate_app`` (those columns stay,
        # vestigial, on old DBs — the kernel simply stops reading them).
        if current < 12:
            existing = await self._session_columns()
            if "app_meta" not in existing:
                await self._db.execute("ALTER TABLE sessions ADD COLUMN app_meta TEXT NOT NULL DEFAULT '{}'")

        # App-owned table migrations (diagnoses / applied_memory_rules, and the
        # app_meta backfill from legacy Odoo columns) — no-op in the base.
        await self._migrate_app(current)

        await self._db.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))

    async def _session_columns(self) -> set[str]:
        """Current column names on the ``sessions`` table."""
        assert self._db is not None
        cols_cur = await self._db.execute("PRAGMA table_info(sessions)")
        cols = await cols_cur.fetchall()
        await cols_cur.close()
        return {str(r[1]) for r in cols}

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def __aenter__(self) -> SqliteStore:
        await self.initialize()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SqliteStore.initialize() not called")
        return self._db

    # ─────────────────────────────── sessions ──────────────────────────────

    async def create_session(
        self,
        *,
        session_id: str,
        customer_id: str,
        status: SessionStatus = "running",
        app_meta: dict[str, Any] | None = None,
    ) -> None:
        """Insert a new session row.

        ``customer_id`` is the opaque per-tenant id (no PII). ``app_meta`` is an
        app-specific scope object persisted as JSON in ``sessions.app_meta`` —
        the kernel treats it opaquely; the migration app stores its
        source/target version + target models there. Defaults to ``{}``
        (sessions without app scope: auto-discovery probes, spikes, etc.).
        """
        db = self._conn()
        app_meta_json = json.dumps(app_meta or {}, ensure_ascii=False, default=str)
        await db.execute(
            """
            INSERT INTO sessions (
                id, customer_id, status, started_at,
                total_input_tokens, total_output_tokens, total_cost_usd, app_meta
            )
            VALUES (?, ?, ?, ?, 0, 0, 0.0, ?)
            """,
            (session_id, customer_id, status, _now(), app_meta_json),
        )
        await db.commit()

    async def update_session(
        self,
        session_id: str,
        *,
        status: SessionStatus | None = None,
        checkpoint: str | None = None,
        input_tokens_delta: int = 0,
        output_tokens_delta: int = 0,
        cost_usd_delta: float = 0.0,
        mark_ended: bool = False,
    ) -> None:
        db = self._conn()
        sets: list[str] = []
        params: list[Any] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if checkpoint is not None:
            sets.append("checkpoint = ?")
            params.append(checkpoint)
        if input_tokens_delta:
            sets.append("total_input_tokens = total_input_tokens + ?")
            params.append(input_tokens_delta)
        if output_tokens_delta:
            sets.append("total_output_tokens = total_output_tokens + ?")
            params.append(output_tokens_delta)
        if cost_usd_delta:
            sets.append("total_cost_usd = total_cost_usd + ?")
            params.append(cost_usd_delta)
        if mark_ended:
            sets.append("ended_at = ?")
            params.append(_now())
        if not sets:
            return
        params.append(session_id)
        await db.execute(f"UPDATE sessions SET {', '.join(sets)} WHERE id = ?", params)
        await db.commit()

    async def get_session(self, session_id: str) -> dict[str, Any] | None:
        db = self._conn()
        async with db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def list_sessions(
        self,
        *,
        customer_id: str | None = None,
        status: SessionStatus | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        db = self._conn()
        clauses: list[str] = []
        params: list[Any] = []
        if customer_id is not None:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        sql = f"SELECT * FROM sessions {where} ORDER BY started_at DESC LIMIT ?"
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    async def set_intervention_type(self, session_id: str, intervention_type: InterventionType) -> None:
        """Classify a session's human-touchpoint outcome. Called once at
        session close by agent_runner. ``none`` means the autonomous
        loop closed without an operator; any other value is one human
        touchpoint and counts against the autonomy zero-intervention bar."""
        db = self._conn()
        await db.execute(
            "UPDATE sessions SET intervention_type = ? WHERE id = ?",
            (intervention_type, session_id),
        )
        await db.commit()

    async def set_outcome(self, session_id: str, outcome: str) -> None:
        """Record a session's honest outcome — aborted | incomplete |
        migrated — computed from session-end verification. Called once at
        session close by agent_runner, after the verify results are in."""
        db = self._conn()
        await db.execute(
            "UPDATE sessions SET outcome = ? WHERE id = ?",
            (outcome, session_id),
        )
        await db.commit()

    async def intervention_summary(self, *, customer_id: str | None = None) -> dict[str, int]:
        """Count sessions per intervention_type — the autonomy product
        metric. Returns every InterventionType key (zero-filled) so a
        consumer can render the full breakdown without missing-key
        guards. Filter by ``customer_id`` for a single tenant's trend;
        omit it for the cross-tenant view.

        The convergence signal: ``none`` rising as a fraction of the
        total across successive accounts means the loop is learning.
        """
        db = self._conn()
        clauses: list[str] = []
        params: list[Any] = []
        if customer_id is not None:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT intervention_type, COUNT(*) AS n FROM sessions {where} GROUP BY intervention_type"
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        summary: dict[str, int] = {
            "none": 0,
            "aborted": 0,
            "novel": 0,
            "stuck": 0,
            "partial": 0,
        }
        for row in rows:
            key = str(row["intervention_type"] or "none")
            if key in summary:
                summary[key] += int(row["n"] or 0)
            else:  # forward-compat: an unknown value still counts somewhere
                summary[key] = int(row["n"] or 0)
        return summary

    # ──────────────────────────────── turns ────────────────────────────────

    async def append_turn(
        self,
        *,
        session_id: str,
        turn_index: int,
        role: TurnRole,
        content_inline: str | None = None,
        content_ref: str | None = None,
        tool_name: str | None = None,
        tool_ok: bool | None = None,
        latency_ms: int | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
    ) -> int:
        db = self._conn()
        cur = await db.execute(
            """
            INSERT INTO turns (
                session_id, turn_index, role,
                content_ref, content_inline,
                tool_name, tool_ok, latency_ms,
                input_tokens, output_tokens, cost_usd, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                turn_index,
                role,
                content_ref,
                content_inline,
                tool_name,
                int(tool_ok) if tool_ok is not None else None,
                latency_ms,
                input_tokens,
                output_tokens,
                cost_usd,
                _now(),
            ),
        )
        await db.commit()
        assert cur.lastrowid is not None  # SQLite always assigns a rowid
        return int(cur.lastrowid)

    async def append_tool_progress(
        self,
        *,
        session_id: str,
        tool_name: str,
        percent: float | None = None,
        message: str | None = None,
    ) -> None:
        """Record a progress tick. Best-effort — never raises."""
        try:
            db = self._conn()
            await db.execute(
                "INSERT INTO tool_progress (session_id, tool_name, percent, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, tool_name, percent, message, _now()),
            )
            await db.commit()
        except Exception as exc:
            log.warning(
                "sqlite.tool_progress_failed",
                session_id=session_id,
                tool=tool_name,
                error=type(exc).__name__,
                message=str(exc)[:300],
            )

    async def search_turns(
        self,
        query: str,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """FTS5 full-text search over turns.

        The caller's query is wrapped as an FTS5 *phrase* so that punctuation
        like ``-``, ``:``, ``.`` stays literal rather than being interpreted
        as FTS5 operators (``-`` would otherwise mean NOT).

        ``session_id`` is an optional filter applied post-FTS.
        """
        db = self._conn()
        phrase = '"' + query.replace('"', '""') + '"'
        clauses = ["turns_fts MATCH ?"]
        params: list[Any] = [phrase]
        if session_id is not None:
            clauses.append("t.session_id = ?")
            params.append(session_id)
        params.append(limit)
        sql = f"""
            SELECT t.*, bm25(turns_fts) AS rank
            FROM turns_fts
            JOIN turns t ON t.id = turns_fts.rowid
            WHERE {" AND ".join(clauses)}
            ORDER BY rank
            LIMIT ?
        """
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return [dict(row) for row in rows]

    # ────────────────────────────── safety + errors ────────────────────────

    async def append_safety_event(
        self,
        *,
        session_id: str,
        kind: SafetyKind,
        turn_id: int | None = None,
        tool_name: str | None = None,
        tool_input: str | None = None,
        detail: str | None = None,
    ) -> int:
        db = self._conn()
        cur = await db.execute(
            """
            INSERT INTO safety_events (
                session_id, turn_id, tool_name, tool_input, kind, detail, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, turn_id, tool_name, tool_input, kind, detail, _now()),
        )
        await db.commit()
        assert cur.lastrowid is not None
        return int(cur.lastrowid)

    async def append_error(
        self,
        *,
        session_id: str,
        error_class: str,
        error_message: str,
        turn_id: int | None = None,
        model: str | None = None,
        external_id: str | None = None,
    ) -> int:
        db = self._conn()
        cur = await db.execute(
            """
            INSERT INTO errors (
                session_id, turn_id, model, external_id, error_class, error_message, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, turn_id, model, external_id, error_class, error_message, _now()),
        )
        await db.commit()
        assert cur.lastrowid is not None
        return int(cur.lastrowid)

    async def count_safety_events(
        self,
        session_id: str,
        *,
        kind: SafetyKind | None = None,
    ) -> int:
        db = self._conn()
        if kind is None:
            sql = "SELECT COUNT(*) FROM safety_events WHERE session_id = ?"
            params: tuple[Any, ...] = (session_id,)
        else:
            sql = "SELECT COUNT(*) FROM safety_events WHERE session_id = ? AND kind = ?"
            params = (session_id, kind)
        async with db.execute(sql, params) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row else 0

    # ───────────────────────── target health (PR-J) ────────────────────────

    async def record_target_health(
        self,
        *,
        url: str,
        ok: bool,
        error_class: str | None = None,
        error_message: str | None = None,
    ) -> int:
        """Append a row to the target_health log; used by the pre-flight
        probe in ``omg migrate`` (PR-J)."""
        db = self._conn()
        cur = await db.execute(
            """
            INSERT INTO target_health (url, ok, error_class, error_message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (url, 1 if ok else 0, error_class, error_message, _now()),
        )
        await db.commit()
        assert cur.lastrowid is not None
        return int(cur.lastrowid)

    async def recent_target_failures(
        self,
        *,
        url: str,
        within_seconds: float = 3600.0,
    ) -> int:
        """Return the count of consecutive most-recent failures for this URL
        within ``within_seconds``. A single success resets the streak.

        Used by the circuit breaker: if this returns ≥ 3, refuse to start
        a new session without ``--force-unhealthy-target``.
        """
        db = self._conn()
        cutoff = (datetime.now(tz=UTC) - timedelta(seconds=within_seconds)).isoformat()
        async with db.execute(
            "SELECT ok FROM target_health WHERE url = ? AND created_at >= ? ORDER BY created_at DESC LIMIT 10",
            (url, cutoff),
        ) as cur:
            rows = await cur.fetchall()
        streak = 0
        for row in rows:
            if int(row[0]) == 0:
                streak += 1
            else:
                break
        return streak
