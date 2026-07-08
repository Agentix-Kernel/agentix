# `storage/` — the three stores

Each store has exactly one job. Don't mix them. (Reference-app physical
layout: `ludo-agent/arch.md` §7.)

- **`minio_store.py`** — async wrapper around MinIO (S3-compatible) for
  bulk blobs: extracts, loads, checkpoints, raw schema snapshots.
  `key_*` helpers own all prefix strings — no concatenation at call
  sites.
- **`sqlite_store.py`** — operational state only (WAL + FTS5):
  sessions, turns, costs, errors, audit, safety events. Schema in
  `docs/sqlite_schema.sql`. Never put domain memory here.
- **`memory.py`** — markdown primitives for the `memory/` directory.
  Section-preserving writes (one H2 at a time, frontmatter untouched);
  `append_to_log` serialises `log.md` behind an asyncio lock. Full
  memory framework: `docs/memory.md`.

## What goes where

| Kind of data | Store |
|---|---|
| Bulk blobs (extracts, loads, checkpoints, snapshots) | MinIO |
| Operational state (sessions, turns, costs, events) | SQLite |
| Domain memory (renames, gotchas, customer pages) | Memory |
