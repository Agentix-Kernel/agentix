# `storage/` — the three stores

Each store has exactly one job. Don't mix them. (Reference-app physical
layout: `ludo-agent/arch.md` §7.)

- **`minio_store.py`** — the blob semantic layer: JSON/JSONL encoding,
  stream composition, `key_*` helpers owning all prefix strings (no
  concatenation at call sites). The raw transport is an
  `ObjectStoreDriver` (`drivers/adapters/minio.py` is the MinIO
  backend); `MinioStore(driver=...)` swaps it. Stores are semantics;
  drivers are transport (`docs/drivers.md` section 5).
- **`sqlite_store.py`** — operational state only (WAL + FTS5):
  sessions, turns, costs, errors, audit, safety events. Schema in
  `docs/sqlite_schema.sql`. Never put domain memory here. The
  connection lives in a `RelationalDriver`
  (`drivers/adapters/sqlite.py`); `SqliteStore(driver=...)` swaps it.
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
