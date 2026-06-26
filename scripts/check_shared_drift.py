#!/usr/bin/env python3
"""check_shared_drift.py — fail if a repo's vendored `ludo_shared/` package has drifted
from the canonical in `ludo-init/libs/python/ludo_shared/`.

`ludo-init/libs/python/ludo_shared/` is the single source of truth for the shared Python
wire types + broker constants + SSE codec (CRIE R-2/R-3/R-4). `_generated.py` is emitted by
`gen_shared.py` from the contracts; consumers vendor a byte-identical copy of the package
under `<repo>/libs/ludo_shared/`. Run from `ludo-init/`. Mirrors check_config_drift.py.
"""
from __future__ import annotations

import filecmp
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent          # ludo-init/
WORKSPACE = REPO_ROOT.parent                                 # /Users/.../s_/ludo
CANON = REPO_ROOT / "libs" / "python" / "ludo_shared"
FILES = ["__init__.py", "_generated.py", "sse.py"]

# Public client (ludo-cli) vendors it too — it is client-safe (no secrets/engine internals).
VENDOR_ROOTS = [
    WORKSPACE / "ludo-agent" / "libs" / "ludo_shared",
    WORKSPACE / "ludo-gateway" / "libs" / "ludo_shared",
    WORKSPACE / "ludo-cli" / "libs" / "ludo_shared",
]


def main() -> int:
    if not CANON.exists():
        print(f"[FAIL] missing canonical: {CANON}", file=sys.stderr)
        return 1
    drift, skipped, ok = [], [], 0
    for root in VENDOR_ROOTS:
        if not root.exists():
            skipped.append(f"not vendored yet: {root}")
            continue
        for name in FILES:
            v = root / name
            if not v.exists():
                drift.append(f"MISSING: {v}")
            elif filecmp.cmp(v, CANON / name, shallow=False):
                ok += 1
            else:
                drift.append(f"DRIFT: {v} != libs/python/ludo_shared/{name}")
    for s in skipped:
        print(f"[skip] {s}")
    for d in drift:
        print(f"[FAIL] {d}", file=sys.stderr)
    print(f"[shared-drift] {ok} in sync, {len(drift)} drifted, {len(skipped)} skipped")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
