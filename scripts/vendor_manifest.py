#!/usr/bin/env python3
"""vendor_manifest.py — the ONE canonical→vendored table for the cluster.

Single source shared by the four drift guards (check_shared_drift, check_internal_drift,
check_config_drift, check_contract_drift) and the re-vendor bot (revendor.py), so the
guard and the bot can never disagree about what is vendored where (Design B,
Ludo-Odoo-Migrations/ludo-agent#558).

Layout notes:
- Paths are expressed workspace-relative (repo-dir/...) and resolved against a workspace
  root — the local sibling checkout by default, a temp clone dir in CI (revendor --workspace).
- `ludo_internal` is INTERNAL-ONLY (CRIE IE-2b): vendored by the private repos, asserted
  ABSENT from the public clients (FORBIDDEN below).
- Desktop hand-codes Swift DTOs from the contract spec — reconciled by review, not byte-diff
  (so contracts have no desktop consumer entry; the generated Swift enums do).
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent  # agentix/
WORKSPACE = REPO_ROOT.parent  # .../ludo


# ---- shared generated + hand-written wire layer (client-safe) -----------------------
# canonical dir (in agentix) -> (filenames, [workspace-relative vendored dirs]).
SHARED_GROUPS: list[tuple[Path, list[str], list[str]]] = [
    (
        REPO_ROOT / "libs" / "python" / "ludo_shared",
        ["__init__.py", "_generated.py", "introspection.py", "sse.py"],
        [
            "ludo-agent/libs/ludo_shared",
            "ludo-gateway/libs/ludo_shared",
            "ludo-cli/libs/ludo_shared",
            "ludo-webapps/backend/libs/ludo_shared",
        ],
    ),
    (
        REPO_ROOT / "libs" / "ts" / "ludo_shared",
        ["generated.js", "generated.d.ts"],
        ["ludo-webapps/libs/ludo_shared"],
    ),
    (
        REPO_ROOT / "libs" / "swift" / "LudoShared",
        ["Generated.swift"],
        ["ludo-desktop/MacOS/app/Sources/LudoDesktop/Generated"],
    ),
]

# Generated artifacts + their generator, for the freshness check (sse.py is hand-written).
GENERATORS: list[tuple[str, Path]] = [
    ("scripts/gen_shared.py", REPO_ROOT / "libs" / "python" / "ludo_shared" / "_generated.py"),
    ("scripts/gen_ts.py", REPO_ROOT / "libs" / "ts" / "ludo_shared" / "generated.js"),
    ("scripts/gen_ts.py", REPO_ROOT / "libs" / "ts" / "ludo_shared" / "generated.d.ts"),
    ("scripts/gen_swift.py", REPO_ROOT / "libs" / "swift" / "LudoShared" / "Generated.swift"),
]

# ---- internal-only NATS transport (private repos; public clients forbidden) ---------
INTERNAL_CANON = REPO_ROOT / "libs" / "internal" / "ludo_internal"
INTERNAL_FILES = ["__init__.py", "nats_streams.py"]
INTERNAL_VENDOR_ROOTS = [
    "ludo-agent/libs/ludo_internal",
    "ludo-gateway/libs/ludo_internal",
]
INTERNAL_FORBIDDEN_ROOTS = [
    "ludo-cli/libs/ludo_internal",
    "ludo-desktop/libs/ludo_internal",
]

# ---- cluster constants ----------------------------------------------------------------
CONFIG_CANON = REPO_ROOT / "constants" / "cluster.yaml"
CONFIG_VENDORS = [
    "ludo-agent/constants/cluster.yaml",
    "ludo-gateway/constants/cluster.yaml",
    "ludo-cli/constants/cluster.yaml",
    "ludo-webapps/constants/cluster.yaml",
]

# ---- contracts --------------------------------------------------------------------------
CONTRACTS_CANON = REPO_ROOT / "contracts"
# workspace-relative consumer copy -> canonical file name in agentix/contracts/
CONTRACT_CONSUMERS: list[tuple[str, str]] = [
    # gateway vendors the full set under the same names
    ("ludo-gateway/contracts/contract_a.openapi.yaml", "contract_a.openapi.yaml"),
    ("ludo-gateway/contracts/contract_c.openapi.yaml", "contract_c.openapi.yaml"),
    ("ludo-gateway/contracts/shared-types.yaml", "shared-types.yaml"),
    ("ludo-gateway/contracts/session-event.schema.json", "session-event.schema.json"),
    ("ludo-gateway/contracts/job-message.schema.json", "job-message.schema.json"),
    # cli vendors Contract A as openapi.yaml + the rest
    ("ludo-cli/contracts/openapi.yaml", "contract_a.openapi.yaml"),
    ("ludo-cli/contracts/shared-types.yaml", "shared-types.yaml"),
    ("ludo-cli/contracts/session-event.schema.json", "session-event.schema.json"),
    ("ludo-cli/contracts/job-message.schema.json", "job-message.schema.json"),
    # webapps vendors Contract B (events) only
    ("ludo-webapps/backend/contract/session-event.schema.json", "session-event.schema.json"),
]


def all_vendored_files(workspace: Path = WORKSPACE) -> list[tuple[Path, Path, str]]:
    """Flatten the whole manifest: (canonical_file, vendored_file, repo_name).

    The re-vendor bot iterates this; the drift guards keep their domain-specific
    reporting but read the same tables above.
    """
    out: list[tuple[Path, Path, str]] = []
    for canon_dir, files, vendor_dirs in SHARED_GROUPS:
        for rel in vendor_dirs:
            repo = rel.split("/", 1)[0]
            for name in files:
                out.append((canon_dir / name, workspace / rel / name, repo))
    for rel in INTERNAL_VENDOR_ROOTS:
        repo = rel.split("/", 1)[0]
        for name in INTERNAL_FILES:
            out.append((INTERNAL_CANON / name, workspace / rel / name, repo))
    for rel in CONFIG_VENDORS:
        out.append((CONFIG_CANON, workspace / rel, rel.split("/", 1)[0]))
    for rel, canon_name in CONTRACT_CONSUMERS:
        out.append((CONTRACTS_CANON / canon_name, workspace / rel, rel.split("/", 1)[0]))
    return out
