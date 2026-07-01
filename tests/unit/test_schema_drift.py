"""CI guard: the reference schema mirror (docs/sqlite_schema.sql) must not drift
from the code-created schema (agentix.storage.sqlite_store._SCHEMA_STATEMENTS).

Both schemas are materialized into in-memory SQLite and compared by TABLE + COLUMN
sets — immune to comments/whitespace/formatting. Indexes and FTS triggers live in
code only and are intentionally excluded (we compare type='table' + columns).
"""

import sqlite3
from pathlib import Path

from agentix.storage.sqlite_store import _SCHEMA_STATEMENTS

_DOC = Path(__file__).resolve().parents[2] / "docs" / "sqlite_schema.sql"


def _tables_and_columns(script: str) -> dict[str, set[str]]:
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(script)
        names = [
            r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        ]
        return {n: {c[1] for c in con.execute(f'PRAGMA table_info("{n}")')} for n in names}
    finally:
        con.close()


def test_doc_sqlite_schema_matches_code() -> None:
    code = _tables_and_columns(";\n".join(_SCHEMA_STATEMENTS) + ";")
    doc = _tables_and_columns(_DOC.read_text())

    missing = {t: sorted(code[t]) for t in code.keys() - doc.keys()}
    extra = {t: sorted(doc[t]) for t in doc.keys() - code.keys()}
    col_diffs = {
        t: {"code_only": sorted(code[t] - doc[t]), "doc_only": sorted(doc[t] - code[t])}
        for t in code.keys() & doc.keys()
        if code[t] != doc[t]
    }
    assert doc == code, (
        "docs/sqlite_schema.sql has drifted from sqlite_store._SCHEMA_STATEMENTS — "
        "update the mirror.\n"
        f"  tables missing from doc: {missing}\n"
        f"  tables only in doc:      {extra}\n"
        f"  column diffs:            {col_diffs}"
    )
