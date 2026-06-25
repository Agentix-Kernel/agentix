# External integrations & links

Single registry of external services + brand/partner links the cluster references. Provider **secret**
keys live in gitignored `.env.<stage>`; this lists the integration points + publishable links.

## Service integrations
| Integration | Purpose | Config (repo) | Notes |
|---|---|---|---|
| **Mollie** | payments (EU/GDPR) | `MOLLIE_API_KEY` (webapps `.env`; `stub`=console) | one-off migration fee + €/day subscription |
| **Odoo** | invoicing (system of record, XML-RPC) | `ODOO_URL/DB/USER/API_KEY` (webapps) | `ODOO_API_KEY` ≠ login password |
| **SCOTCH** | source-Odoo scan / X-Ray feeding the estimate | `SCOTCH_URL/API_TOKEN` (webapps; `stub`) | |
| **GitHub / LinkedIn OAuth** | sign-in | `*_OAUTH_CLIENT_ID/SECRET` (webapps; gateway post-cutover) | callbacks: `https://runludo.com/api/v1/auth/{github,linkedin}/callback` |
| **IONOS** | DNS reconciliation | API key outside git (`~/.claude/credentials.json`) | see webapps `docs/dns.md` |
| **Brevo / Mauxy / Email.js** | email + newsletter + forms | — | see [`email-and-notifications.md`](email-and-notifications.md) |
| **LLM providers** | the Cortex | `ANTHROPIC` (primary) / `OPENAI` / `GROQ` (agent) | agent-only; OAuth via `~/.claude/.credentials.json` for Claude |

## Brand / partner links (publishable — single source: `web-ui/.../ludo-env.js`)
- GitHub: `https://github.com/simplify-erp/ludo` · LinkedIn: `https://linkedin.com/company/simplify-erp`
- Partners: ReCloud `https://re-cloud.io/` · Odoo `https://www.odoo.com/` · Melious `https://melious.ai/`

## Repo GitHub map
`ludo-agent`→`euroblaze/ludo` · `ludo-gateway`→`euroblaze/ludo-gateway` ·
`ludo-webapps`→`euroblaze/ludo-flywheel` · `ludo-cli`→`euroblaze/ludo-omg` ·
`ludo-desktop`→`euroblaze/ludo-desktop` · `ludo-init`→`euroblaze/ludo-init`. (Also in `../CLAUDE.md`.)
