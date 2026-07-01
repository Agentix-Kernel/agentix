# `storage/` — the three stores

Per arch.md §7, each store has exactly one job. Don't mix them.

- **`minio_store.py`** — async wrapper around MinIO (S3-compatible) for
  bulk blobs: extracts, loads, checkpoints, raw schema snapshots.
  `key_*` helpers own all prefix strings — no concatenation at call
  sites. Bucket layout in arch.md §7.1.
- **`sqlite_store.py`** — operational state only (WAL + FTS5):
  sessions, turns, costs, errors, audit, safety events. Schema in
  arch.md §7.2. Never put domain memory here.
- **`memory.py`** — markdown primitives for the `memory/` directory.
  Section-preserving writes (one H2 at a time, frontmatter untouched);
  `append_to_log` serialises `log.md` behind an asyncio lock.

## What goes where

| Kind of data | Store |
|---|---|
| Bulk blobs (extracts, loads, checkpoints, snapshots) | MinIO |
| Operational state (sessions, turns, costs, events) | SQLite |
| Domain memory (renames, gotchas, customer pages) | Memory |
