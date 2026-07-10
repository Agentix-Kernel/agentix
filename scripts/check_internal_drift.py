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

from vendor_manifest import INTERNAL_CANON as CANON
from vendor_manifest import INTERNAL_FILES as FILES
from vendor_manifest import (
    INTERNAL_FORBIDDEN_ROOTS,
    INTERNAL_VENDOR_ROOTS,
    REPO_ROOT,
    WORKSPACE,
)

# Vendor + forbidden lists come from the shared manifest (vendor_manifest.py) — one
# table for the guards AND the re-vendor bot (revendor.py). Private repos ONLY vendor
# this; the public clients are asserted absent (positive boundary check).
VENDOR_ROOTS = [WORKSPACE / rel for rel in INTERNAL_VENDOR_ROOTS]
FORBIDDEN_ROOTS = [WORKSPACE / rel for rel in INTERNAL_FORBIDDEN_ROOTS]


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
