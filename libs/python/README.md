# libs/python — canonical shared Python code

`ludo_shared/` is the single source of truth for cross-repo Python wire types, broker
constants, and the SSE codec (CRIE R-2 / R-3 / R-4 / C-5).

- `_generated.py` — **auto-generated** by [`../../scripts/gen_shared.py`](../../scripts/gen_shared.py)
  from `contracts/*.schema.json` + `constants/cluster.yaml`. Never hand-edit; regenerate.
- `sse.py` — hand-written SSE encode/decode (Contract A wire format).
- `__init__.py` — public surface.

## Vendoring
Python consumers **vendor a byte-identical copy** of the whole package under
`<repo>/libs/ludo_shared/` (same model as `contracts/` and `constants/cluster.yaml`). Drift is
guarded by [`../../scripts/check_shared_drift.py`](../../scripts/check_shared_drift.py).

Consumers: `ludo-agent`, `ludo-gateway` (private), `ludo-cli` (public — the package is
client-safe: no secrets, no engine internals). The **internal** NATS broker client is NOT in
here; it stays between the private repos only (CRIE IE-2).

## Regenerate
```
python scripts/gen_shared.py          # needs PyYAML; consumers' pydantic is the runtime dep
python scripts/check_shared_drift.py  # verify vendored copies are in sync
```
After regenerating, re-vendor the copies into each consumer.
