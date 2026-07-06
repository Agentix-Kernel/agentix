#!/usr/bin/env python3
"""check_internal_drift.py — fail if a private repo's vendored `ludo_internal/` package has
drifted from the canonical in `agentix/libs/internal/ludo_internal/`.

`ludo_internal` is INTERNAL-ONLY shared NATS transport (CRIE IE-2b). Unlike `ludo_shared`
(client-safe, vendored by the public cli too), this is vendored **only by the private repos**
— `ludo-agent` + `ludo-gateway`. The public clients (`ludo-cli`/`ludo-desktop`) must NEVER
vendor it; this guard's vendor list deliberately omits them. Run from `agentix/`.
"""
from __future__ import annotations

import filecmp
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent          # agentix/
WORKSPACE = REPO_ROOT.parent                                 # /Users/.../s_/ludo
CANON = REPO_ROOT / "libs" / "internal" / "ludo_internal"
FILES = ["__init__.py", "nats_streams.py"]

# Private repos ONLY — public clients must not vendor internal broker code.
VENDOR_ROOTS = [
    WORKSPACE / "ludo-agent" / "libs" / "ludo_internal",
    WORKSPACE / "ludo-gateway" / "libs" / "ludo_internal",
]

# Public clients that must NOT carry it (asserted absent — a positive boundary check).
FORBIDDEN_ROOTS = [
    WORKSPACE / "ludo-cli" / "libs" / "ludo_internal",
    WORKSPACE / "ludo-desktop" / "libs" / "ludo_internal",
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
                drift.append(f"DRIFT: {v} != {(CANON / name).relative_to(REPO_ROOT)}")
    for root in FORBIDDEN_ROOTS:
        if root.exists():
            drift.append(f"BOUNDARY: internal code vendored into a PUBLIC client: {root}")
    for s in skipped:
        print(f"[skip] {s}")
    for d in drift:
        print(f"[FAIL] {d}", file=sys.stderr)
    print(f"[internal-drift] {ok} in sync, {len(drift)} problem(s), {len(skipped)} skipped")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
