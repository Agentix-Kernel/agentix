# Deployment domains

Canonical per-stage domains live in [`../constants/cluster.yaml`](../constants/cluster.yaml)
(`domains:`). Explicit `.env.<stage>` values always win (12-factor).

| Stage | Public | Portal | Superadmin | API |
|---|---|---|---|---|
| **prod** | `https://runludo.com` | `…/portal` | `https://superadmin.runludo.com` | `…/api/v1` (apex) |
| **stag** | `https://ludo.stag.simplify-erp.de` | `…/portal` | `superadmin.<stag zone>` | `…/api/v1` |
| **dev** | `http://10.0.99.1:8080` | `…/portal` | `http://10.0.99.1:8092` | `http://10.0.99.1:8000/api/v1` |

## Zone rules
- **Apex** serves public + portal (`/portal`) + API (`/api/v1` proxied) — one origin (same-origin
  model, see [`cors-strategy.md`](cors-strategy.md)).
- **Superadmin** is its own subdomain. `ludo-env.js` derives it by stripping a leading
  `superadmin.|portal.|api.|www.` label from the current host (NOT `indexOf("ludo.")`, which would
  mis-parse `runludo.com`).
- **OAuth callback URLs** (publishable) are apex-based, e.g.
  `https://runludo.com/api/v1/auth/{github,linkedin}/callback`; `AUTH_SUCCESS_REDIRECT` is set
  explicitly in stag/prod (not derived), e.g. `https://runludo.com/portal/#/login`.
- **Ingress LB IPs** per stage (`INGRESS_IP_DEV/STAG/PROD`, not secrets) feed `infra/dns/records.yaml`
  in webapps; DNS reconciliation uses an IONOS key kept out of git.
