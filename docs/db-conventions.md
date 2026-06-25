# Database conventions

## Engine choice
Single-writer **SQLite (WAL)** in all envs for the gateway control-plane store
(ADR: `ludo-gateway/docs/decisions/0001-sqlite-single-writer.md`). The agent keeps its own
SQLite+FTS5 for ops state (separate DB, never shared). Postgres is reopenable via a one-line
`DATABASE_URL` swap (the ORM is dialect-agnostic) if active-active writes are ever needed.

## Pragmas (SQLite)
`journal_mode=WAL` · `busy_timeout=5000` · `synchronous=NORMAL` · `foreign_keys=ON`
(set per-connection). WAL = concurrent readers never block the lone writer.

## Per-env files
One DB file per stage, never shared across services:
- gateway: `sqlite:///./data/gateway_<stage>.db`
- webapps: `data/sqlite/ludo_<stage>.db`
- agent: its own ops `*.db`
`DATABASE_URL` (gateway) / `SQLITE_DB` (webapps) override.

## Backups
`<repo>/data/[sqlite|pg]_backups/`. SQLite backup = WAL-checkpoint + `VACUUM INTO` a timestamped
file (see each repo's `scripts/sqlite_db.py`). Litestream (sidecar → MinIO) is the recommended
continuous warm-standby / PITR for prod.

## Migrations
**Alembic** (works on SQLite; `render_as_batch=True` for column ALTERs). `create_all` is the dev/CI
safety net; Alembic is the deploy path. Dates are date objects end-to-end (no string timestamps).
