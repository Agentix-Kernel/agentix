-- Agentix kernel — SQLite schema (reference mirror)
--
-- SOURCE OF TRUTH: src/agentix/storage/sqlite_store.py (`_SCHEMA_STATEMENTS`) — created in code.
-- Drift-checked mirror (tests/unit/test_schema_drift.py); regenerate when the code schema
-- changes. Schema version: 12. App-specific tables (the migration app's
-- `diagnoses` / `applied_memory_rules`) live in ludo.storage.ludo_sqlite, not here.

CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL,
        applied_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
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
        -- opaquely; apps read their own keys (the migration app stores
        -- source_version / target_version / target_models here). '{}' = no
        -- app scope (auto-discovery / spike / probe). NOT NULL with a default
        -- so the column read is always safe.
        app_meta TEXT NOT NULL DEFAULT '{}',
        -- Human-touchpoint classification for this session — the autonomy
        -- product metric. Counts of non-'none' values per account show whether
        -- the autonomous loop is converging. Written at session close.
        intervention_type TEXT NOT NULL DEFAULT 'none',
        -- Honest session outcome label, derived from session-end verification
        -- rather than the agent's terminal message. NULL until computed at
        -- session close; rows that predate it stay NULL (unjudged).
        outcome TEXT,
        -- Control-plane binding: the gateway-assigned Migration id
        -- (``ludo_session_id``) this Session runs. NULL for local runs.
        control_plane_id TEXT,
        -- A2A delegation link: the Session that spawned this one (self-ref).
        -- NULL for top-level runs.
        parent_session_id TEXT REFERENCES sessions(id)
    );
CREATE INDEX IF NOT EXISTS idx_sessions_customer ON sessions (customer_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions (status);
CREATE INDEX IF NOT EXISTS idx_sessions_control_plane ON sessions (control_plane_id) WHERE control_plane_id IS NOT NULL;
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
    );
CREATE INDEX IF NOT EXISTS idx_turns_session ON turns (session_id, turn_index);
CREATE TABLE IF NOT EXISTS safety_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        turn_id INTEGER REFERENCES turns(id) ON DELETE SET NULL,
        tool_name TEXT,
        tool_input TEXT,
        kind TEXT NOT NULL,
        detail TEXT,
        created_at TEXT NOT NULL
    );
CREATE INDEX IF NOT EXISTS idx_safety_events_session ON safety_events (session_id, kind);
CREATE TABLE IF NOT EXISTS errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        turn_id INTEGER REFERENCES turns(id) ON DELETE SET NULL,
        model TEXT,
        external_id TEXT,
        error_class TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL
    );
CREATE INDEX IF NOT EXISTS idx_errors_session ON errors (session_id);
CREATE TABLE IF NOT EXISTS target_health (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT NOT NULL,
        ok INTEGER NOT NULL,
        error_class TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL
    );
CREATE INDEX IF NOT EXISTS idx_target_health_url_time ON target_health (url, created_at);
CREATE TABLE IF NOT EXISTS tool_progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        tool_name TEXT NOT NULL,
        percent REAL,
        message TEXT,
        created_at TEXT NOT NULL
    );
CREATE INDEX IF NOT EXISTS idx_tool_progress_session ON tool_progress (session_id, created_at);
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
        session_id,
        tool_name,
        content_inline,
        content='turns',
        content_rowid='id',
        tokenize='unicode61 remove_diacritics 2'
    );
CREATE TRIGGER IF NOT EXISTS turns_ai AFTER INSERT ON turns BEGIN
        INSERT INTO turns_fts (rowid, session_id, tool_name, content_inline)
        VALUES (new.id, new.session_id, COALESCE(new.tool_name, ''), COALESCE(new.content_inline, ''));
    END;
CREATE TRIGGER IF NOT EXISTS turns_ad AFTER DELETE ON turns BEGIN
        INSERT INTO turns_fts (turns_fts, rowid, session_id, tool_name, content_inline)
        VALUES ('delete', old.id, old.session_id, COALESCE(old.tool_name, ''), COALESCE(old.content_inline, ''));
    END;
CREATE TRIGGER IF NOT EXISTS turns_au AFTER UPDATE ON turns BEGIN
        INSERT INTO turns_fts (turns_fts, rowid, session_id, tool_name, content_inline)
        VALUES ('delete', old.id, old.session_id, COALESCE(old.tool_name, ''), COALESCE(old.content_inline, ''));
        INSERT INTO turns_fts (rowid, session_id, tool_name, content_inline)
        VALUES (new.id, new.session_id, COALESCE(new.tool_name, ''), COALESCE(new.content_inline, ''));
    END;
