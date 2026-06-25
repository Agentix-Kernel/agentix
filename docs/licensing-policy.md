# Licensing policy

Two tiers, aligned to repo visibility. **Proprietary** (closed, *private* repos) for the engine,
the gateway edge, and the product frontends; **source-available** (BSL 1.1 → Apache-2.0) for the
two *public* client repos. BSL ≠ OSI open-source: source is visible + modifiable for
**non-production** use; production needs a commercial license until the Change Date, when it
converts to Apache-2.0.

| Repo (dir) | GitHub | License | Visibility |
|---|---|---|---|
| ludo-agent | euroblaze/ludo-agent | **Proprietary** — all rights reserved | private |
| ludo-gateway | euroblaze/ludo-gateway | **Proprietary** — all rights reserved | private |
| ludo-webapps | euroblaze/ludo-webapps | **Proprietary** — all rights reserved | private |
| ludo-cli | euroblaze/ludo-cli | **BSL 1.1 → Apache-2.0** | public |
| ludo-desktop | euroblaze/ludo-desktop | **BSL 1.1 → Apache-2.0** | public |

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
- **2026-06-25 (corrected):** the proprietary perimeter is `ludo-agent`, `ludo-gateway`,
  `ludo-webapps` (all private). Only the public client repos `ludo-cli` + `ludo-desktop` are
  BSL 1.1. This supersedes an earlier same-day note that had moved `ludo-agent` (and implied
  `ludo-gateway`) to BSL.
- **Action required (on-disk drift):** `ludo-agent/LICENSE` and `ludo-gateway/LICENSE` still
  carry BSL 1.1 text, and `ludo-agent/pyproject.toml` declares `BUSL-1.1`. These legal files
  must be flipped to the proprietary notice to match this policy. Held pending owner go-ahead
  (reverses a same-day decision). Tracked as CRIE C-1.
