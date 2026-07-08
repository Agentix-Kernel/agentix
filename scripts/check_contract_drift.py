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

REPO_ROOT = Path(__file__).resolve().parent.parent          # agentix/
WORKSPACE = REPO_ROOT.parent                                 # /Users/.../s_/ludo
CANON = REPO_ROOT / "contracts"

GATEWAY = WORKSPACE / "ludo-gateway" / "contracts"
CLI = WORKSPACE / "ludo-cli" / "contracts"
WEBAPPS = WORKSPACE / "ludo-webapps" / "backend" / "contract"

# consumer_copy -> canonical file name in agentix/contracts/
CONSUMERS: list[tuple[Path, str]] = [
    # gateway vendors the full set under the same names
    (GATEWAY / "contract_a.openapi.yaml", "contract_a.openapi.yaml"),
    (GATEWAY / "contract_c.openapi.yaml", "contract_c.openapi.yaml"),
    (GATEWAY / "shared-types.yaml", "shared-types.yaml"),
    (GATEWAY / "session-event.schema.json", "session-event.schema.json"),
    (GATEWAY / "job-message.schema.json", "job-message.schema.json"),
    # cli vendors Contract A as openapi.yaml + the rest
    (CLI / "openapi.yaml", "contract_a.openapi.yaml"),
    (CLI / "shared-types.yaml", "shared-types.yaml"),
    (CLI / "session-event.schema.json", "session-event.schema.json"),
    (CLI / "job-message.schema.json", "job-message.schema.json"),
    # webapps vendors Contract B (events) only
    (WEBAPPS / "session-event.schema.json", "session-event.schema.json"),
]


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
