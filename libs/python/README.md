# libs/python — canonical shared Python code

> Cross-language siblings: **`../ts/ludo_shared/`** (JS, via `scripts/gen_ts.py`) and
> **`../swift/LudoShared/`** (Swift, via `scripts/gen_swift.py`) emit the same enums +
> migration lifecycle for the public JS/Swift clients (client-safe: enums only, no broker
> internals). All three read the same `contracts/` + `constants/cluster.yaml` so the wire
> types + `MIGRATION_STATES` can never drift across languages (CRIE 002 #8 / #101).

`ludo_shared/` is the single source of truth for cross-repo Python wire types, broker
constants, the migration lifecycle, and the SSE codec (CRIE R-2 / R-3 / R-4 / C-5).

- `_generated.py` — **auto-generated** by [`../../scripts/gen_shared.py`](../../scripts/gen_shared.py)
  from `contracts/*.schema.json` + `constants/cluster.yaml`. Never hand-edit; regenerate.
- `sse.py` — hand-written SSE encode/decode (Contract A wire format).
- `__init__.py` — public surface.

## Vendoring
Python consumers **vendor a byte-identical copy** of the whole package under
`<repo>/libs/ludo_shared/` (same model as `contracts/` and `constants/cluster.yaml`). Drift is
guarded by [`../../scripts/check_shared_drift.py`](../../scripts/check_shared_drift.py).

Consumers: `ludo-agent`, `ludo-gateway`, `ludo-webapps/backend` (private), `ludo-cli`
(public — the package is client-safe: no secrets, no engine internals). The **internal** NATS
broker client is NOT in here; it stays between the private repos only (CRIE IE-2). The JS/Swift
artifacts are vendored by `ludo-webapps` (frontend) and `ludo-desktop` respectively.

## Regenerate
```
python scripts/gen_shared.py          # Python  -> libs/python/ludo_shared/_generated.py
python scripts/gen_ts.py              # JS      -> libs/ts/ludo_shared/generated.{js,d.ts}
python scripts/gen_swift.py           # Swift   -> libs/swift/LudoShared/Generated.swift
python scripts/check_shared_drift.py  # verify vendored copies in sync + codegen is fresh
```
All three generators need PyYAML; consumers' pydantic is the Python runtime dep. After
regenerating, re-vendor the copies into each consumer.
