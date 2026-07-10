#!/usr/bin/env python3
"""check_contract_drift.py — fail if a consumer's vendored contract copy has drifted
from the canonical set in `agentix/contracts/`.

`agentix/contracts/` is the single source of truth (docs/contracts.md). Clients
vendor copies; this guards they stay byte-identical. Run from `agentix/` in CI / before
a release. Best-effort: a sibling repo not checked out is skipped (reported), not a failure.

Covered: ludo-gateway, ludo-cli, ludo-webapps (file-vendored). Desktop hand-codes Swift
DTOs from the spec — reconciled by review at cutover, not by this byte diff.
"""

from __future__ import annotations

import filecmp
import sys
from pathlib import Path

from vendor_manifest import CONTRACT_CONSUMERS, WORKSPACE
from vendor_manifest import CONTRACTS_CANON as CANON

# Consumer table comes from the shared manifest (vendor_manifest.py) — one table
# for the guards AND the re-vendor bot (revendor.py), so they can never disagree.
CONSUMERS: list[tuple[Path, str]] = [(WORKSPACE / rel, canon_name) for rel, canon_name in CONTRACT_CONSUMERS]


def main() -> int:
    drift, skipped, ok = [], [], 0
    for copy, canon_name in CONSUMERS:
        canon = CANON / canon_name
        if not canon.exists():
            drift.append(f"MISSING CANONICAL: {canon}")
            continue
        if not copy.exists():
            skipped.append(f"absent (repo not checked out / not yet vendored?): {copy}")
            continue
        if filecmp.cmp(copy, canon, shallow=False):
            ok += 1
        else:
            drift.append(f"DRIFT: {copy}  !=  contracts/{canon_name}")

    for s in skipped:
        print(f"[skip] {s}")
    for d in drift:
        print(f"[FAIL] {d}", file=sys.stderr)
    print(f"[contract-drift] {ok} in sync, {len(drift)} drifted, {len(skipped)} skipped")
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
