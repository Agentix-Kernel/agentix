# Environment & secrets

## Env-stage pattern (all services)
`APP_ENV` selects the env file `.env.<APP_ENV>` with `.env` as fallback; stages are
`dev | stag | prod` (default `dev`). Pattern used by gateway + webapps backends; the agent layers
`.env` similarly under its `LUDO_CONFIG` yaml. Shared keys: [`../templates/env.template`](../templates/env.template).
Service-specific keys (provider API keys, vault, Mollie/Odoo/Brevo, OAuth) stay in each repo's `.env.example`.

## Secret policy — fail fast in stag/prod
Real secrets live **only** in gitignored `.env.<stage>`; never committed. The insecure dev
placeholders are in `cluster.yaml:dev_secret_placeholders`. **stag/prod must refuse to start on a
placeholder** (forgeable JWTs / readable vault otherwise):
- gateway: `Settings._guard_prod_secret` rejects the default `JWT_SECRET` in stag/prod.
- webapps: a model-validator rejects default `VAULT_ENC_KEY` / `VAULT_ENC_SALT` in stag/prod.
- agent: **does not yet have this guard** — flagged to adopt the same pattern (follow-up).

## Secret vs publishable
| Class | Examples | Where |
|---|---|---|
| **Secret** (never commit) | `JWT_SECRET`, `VAULT_ENC_KEY/SALT`, `SUPERADMIN_PASSWORD`, `MOLLIE_API_KEY`, `BREVO_API_KEY`, `ODOO_API_KEY`, OAuth client secrets, provider LLM keys (ANTHROPIC/OPENAI/GROQ) | gitignored `.env.<stage>`; prod via KMS |
| **Publishable** (safe in client/git) | Email.js public-key, Mauxy publishable site key, OAuth **callback URLs**, ingress IPs, domains | frontend (`ludo-env.js`) / docs — see [`email-and-notifications.md`](email-and-notifications.md) |

DB conventions: [`db-conventions.md`](db-conventions.md). Logging: [`logging.md`](logging.md).
