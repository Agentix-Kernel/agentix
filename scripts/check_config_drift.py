#!/usr/bin/env python3
"""check_config_drift.py — fail if a repo's vendored `constants/cluster.yaml` has
drifted from the canonical in `agentix/constants/`.

`agentix/constants/cluster.yaml` is the single source of truth for shared values
(loopback, ports, NATS subjects/streams, env stages, dev placeholders, tooling
baseline). Each Python repo vendors a byte-identical copy under `<repo>/constants/`.
Run from `agentix/`. Sibling-style guard, mirroring check_contract_drift.py.

(ruff config + .gitignore base are aligned in-place per repo — their tiers differ —
so they're not byte-vendored here; ludo-agent/docs/cluster/dev-standards.md is their canonical reference.)
"""

from __future__ import annotations

import filecmp
import sys

from vendor_manifest import CONFIG_CANON as CANON
from vendor_manifest import CONFIG_VENDORS, WORKSPACE

# Vendored copies come from the shared manifest (vendor_manifest.py) — one table
# for the guards AND the re-vendor bot (revendor.py), so they can never disagree.
VENDORS = [WORKSPACE / rel for rel in CONFIG_VENDORS]


def main() -> int:
    if not CANON.exists():
        print(f"[FAIL] missing canonical: {CANON}", file=sys.stderr)
        return 1
    drift, skipped, ok = [], [], 0
    for v in VENDORS:
        if not v.exists():
            skipped.append(f"not vendored yet: {v}")
            continue
        if filecmp.cmp(v, CANON, shallow=False):
            ok += 1
        else:
            drift.append(f"DRIFT: {v} != constants/cluster.yaml")
    for s in skipped:
        print(f"[skip] {s}")
    for d in drift:
        print(f"[FAIL] {d}", file=sys.stderr)
    print(f"[config-drift] {ok} in sync, {len(drift)} drifted, {len(skipped)} skipped")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
