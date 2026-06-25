# ludo-init — LUDO cluster foundation

The **bootstrap + foundation** repo for the LUDO product cluster (autonomous Odoo cross-version
migration). It holds what's shared across all repos: the cross-repo hub, the unified product PRD,
the canonical **contracts** (seams), shared **constants** + config **templates**, and cluster-level
docs. Start here, then defer to each repo's own `CLAUDE.md`/README for specifics.

## What's here
| Path | What |
|---|---|
| `CLAUDE.md` | Cross-repo hub: shared vocabulary, topology, agentic surface, repo map |
| `LUDO-PRD-Unified.md` | Unified product PRD (product · architecture · orchestration) |
| `contracts/` | Canonical Contract A/B/C + shared types (vendored by consumers; drift-checked) |
| `constants/cluster.yaml` | **Single source** for shared values (loopback, ports, NATS, env stages, domains, locale) |
| `templates/` | `gitignore.base` · `ruff.toml` · `env.template` — vendored/aligned into repos |
| `docs/` | Cluster architecture, contracts consumer guide, proposals, + config/policy docs (network, env-and-secrets, tooling, db, cors, docker, domains, email, integrations, licensing, logging) |
| `scripts/` | `check_contract_drift.py` · `check_config_drift.py` — guard vendored copies |
| `LICENSE` | Canonical BSL 1.1 (see `docs/licensing-policy.md` for the per-repo tier matrix) |

## The cluster (repo map)
| Dir | GitHub | Role |
|---|---|---|
| `ludo-agent` | euroblaze/ludo | migration engine + worker (internal-only; the only agentic component) |
| `ludo-gateway` | euroblaze/ludo-gateway | public control-plane edge (the single public door over the broker) |
| `ludo-webapps` | euroblaze/ludo-flywheel | product frontends (Vue 3 + Vite); backend retiring into the gateway |
| `ludo-cli` | euroblaze/ludo-omg | transport-only CLI client |
| `ludo-desktop` | euroblaze/ludo-desktop | native SwiftUI desktop client (macOS) |
| `ludo-init` | euroblaze/ludo-init | **this repo** — cluster foundation |

## Workspace setup
1. **Clone** all repos as siblings under one workspace dir (e.g. `~/s_/ludo/`); clone `ludo-init`
   first (it carries the shared contracts/constants the others vendor).
2. **Prerequisites:** Python **3.12** + **uv**, Node.js (frontends), Docker (+ compose), NATS for the
   broker path. macOS client needs Xcode 15+.
3. **Per-repo setup:** follow each repo's README (`uv sync` for Python services; `npm install` +
   `npm run dev` for `ludo-webapps`). Conventions: [`docs/tooling-standards.md`](docs/tooling-standards.md),
   [`docs/network-and-ports.md`](docs/network-and-ports.md), [`docs/env-and-secrets.md`](docs/env-and-secrets.md).
4. **Vendored config:** repos copy `constants/cluster.yaml` (+ align `ruff`/`.gitignore` to
   `templates/`); `scripts/check_config_drift.py` and `check_contract_drift.py` keep copies honest.

## Conventions in one line
Loopback `10.0.99.1` (never localhost) · `APP_ENV`→`.env.<stage>` · SQLite WAL single-writer ·
ruff line-length 120 · EUR · German backend default / English fallback. Change shared values in
`constants/cluster.yaml`, then re-vendor.
