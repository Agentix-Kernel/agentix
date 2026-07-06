#!/usr/bin/env python3
"""check_shared_drift.py — fail if a repo's vendored shared package drifted from the
canonical in `agentix`, or if the generated artifacts are stale vs their sources.

`agentix/libs/` is the single source of truth for the shared, cross-repo wire types +
migration lifecycle (CRIE R-2/R-3/R-4 + 002 #8/#101). The generated artifacts are emitted
by gen_shared.py (Python) / gen_ts.py (JS) / gen_swift.py (Swift) from `contracts/` +
`constants/cluster.yaml`; consumers vendor a byte-identical copy. This guard checks:

  1. drift   — every vendored copy is byte-identical to the canonical, per language.
  2. freshness (CRIE IE-6) — re-running the generators changes nothing (i.e. the canonical
     artifacts were regenerated after the last contract/cluster edit).

Run from `agentix/`. Mirrors check_config_drift.py.
"""
from __future__ import annotations

import filecmp
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent          # agentix/
WORKSPACE = REPO_ROOT.parent                                 # /Users/.../s_/ludo
LIBS = REPO_ROOT / "libs"

# canonical dir -> (filenames, [vendored copies of that dir]).
# Python is vendored by agent/gateway/cli (private + the public cli) + the webapps backend.
# JS (client-safe: enums only) by the webapps frontend. Swift by the public desktop client.
GROUPS = [
    (
        LIBS / "python" / "ludo_shared",
        ["__init__.py", "_generated.py", "sse.py"],
        [
            WORKSPACE / "ludo-agent" / "libs" / "ludo_shared",
            WORKSPACE / "ludo-gateway" / "libs" / "ludo_shared",
            WORKSPACE / "ludo-cli" / "libs" / "ludo_shared",
            WORKSPACE / "ludo-webapps" / "backend" / "libs" / "ludo_shared",
        ],
    ),
    (
        LIBS / "ts" / "ludo_shared",
        ["generated.js", "generated.d.ts"],
        [WORKSPACE / "ludo-webapps" / "libs" / "ludo_shared"],
    ),
    (
        LIBS / "swift" / "LudoShared",
        ["Generated.swift"],
        [WORKSPACE / "ludo-desktop" / "MacOS" / "app" / "Sources" / "LudoDesktop" / "Generated"],
    ),
]

# Generated artifacts + their generator, for the freshness check (hand-written sse.py excluded).
GENERATORS = [
    ("scripts/gen_shared.py", LIBS / "python" / "ludo_shared" / "_generated.py"),
    ("scripts/gen_ts.py", LIBS / "ts" / "ludo_shared" / "generated.js"),
    ("scripts/gen_ts.py", LIBS / "ts" / "ludo_shared" / "generated.d.ts"),
    ("scripts/gen_swift.py", LIBS / "swift" / "LudoShared" / "Generated.swift"),
]


def check_drift() -> list[str]:
    drift, skipped, ok = [], [], 0
    for canon, files, vendors in GROUPS:
        if not canon.exists():
            drift.append(f"missing canonical: {canon}")
            continue
        for root in vendors:
            if not root.exists():
                skipped.append(f"not vendored yet: {root}")
                continue
            for name in files:
                v = root / name
                if not v.exists():
                    drift.append(f"MISSING: {v}")
                elif filecmp.cmp(v, canon / name, shallow=False):
                    ok += 1
                else:
                    drift.append(f"DRIFT: {v} != {(canon / name).relative_to(REPO_ROOT)}")
    for s in skipped:
        print(f"[skip] {s}")
    print(f"[shared-drift] {ok} in sync, {len(drift)} drifted, {len(skipped)} skipped")
    return drift


def check_freshness() -> list[str]:
    """Re-run the generators; a changed artifact means a source edit wasn't regenerated."""
    before = {out: out.read_bytes() for _, out in GENERATORS if out.exists()}
    scripts = sorted({s for s, _ in GENERATORS})
    for script in scripts:
        subprocess.run([sys.executable, script], cwd=REPO_ROOT, check=True,
                       capture_output=True)
    stale = []
    for _, out in GENERATORS:
        if out.read_bytes() != before.get(out):
            stale.append(f"STALE: {out.relative_to(REPO_ROOT)} — re-run its generator + re-vendor")
    print(f"[codegen-fresh] {len(GENERATORS) - len(stale)}/{len(GENERATORS)} up to date")
    return stale


def main() -> int:
    problems = check_drift() + check_freshness()
    for p in problems:
        print(f"[FAIL] {p}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
