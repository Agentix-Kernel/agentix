# Licensing policy

Two tiers. **Source-available** (BSL 1.1 → Apache-2.0) for the engine, the gateway edge, and the
clients; **closed/proprietary** for the product frontends (`ludo-webapps`). BSL ≠ OSI open-source:
source is visible + modifiable for **non-production** use; production needs a commercial license until
the Change Date, when it converts to Apache-2.0.

| Repo (dir) | GitHub | License |
|---|---|---|
| ludo-agent | euroblaze/ludo | **BSL 1.1 → Apache-2.0** |
| ludo-webapps | euroblaze/ludo-flywheel | **Proprietary** — all rights reserved |
| ludo-gateway | euroblaze/ludo-gateway | **BSL 1.1 → Apache-2.0** |
| ludo-cli | euroblaze/ludo-omg | **BSL 1.1 → Apache-2.0** |
| ludo-desktop | euroblaze/ludo-desktop | **BSL 1.1 → Apache-2.0** |

## BSL parameters (canonical)
- **Licensor:** wapsol (labs) gmbh · © 2026 wapsol (labs) gmbh.
- **Additional Use Grant:** None.
- **Change Date:** the fourth anniversary of the first public distribution of each version.
- **Change License:** Apache License 2.0.
- **Commercial / alternative licensing:** contact **Ashant Chalasani <ach@runludo.com>**.

The canonical BSL text is [`../LICENSE`](../LICENSE); each BSL repo's `LICENSE` is the same text with
its own `Licensed Work:` line. Proprietary repos carry the short proprietary notice. Keep the contact
+ Change Date here (single source) — repos reference this policy.

## History
`ludo-agent` was previously proprietary and its `pyproject.toml` mis-declared `license = "MIT"`.
It is now **BSL 1.1** (decision: 2026-06-25): LICENSE + `pyproject.toml` (`BUSL-1.1`) + the repo's
`CLAUDE.md`/`arch.md` notes were aligned. Only `ludo-webapps` remains proprietary.
