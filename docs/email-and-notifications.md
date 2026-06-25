# Email & notifications

Canonical registry of the cluster's email/notification providers. **Publishable** IDs are listed
here (safe in client code / git by design); **secret** API keys live only in gitignored `.env.<stage>`
(see [`env-and-secrets.md`](env-and-secrets.md)).

| Channel | Provider | Mode | Keys |
|---|---|---|---|
| Transactional (migration status, support replies, shares) | **Brevo** | server-side; `stub` = console (dev/CI) | `BREVO_API_KEY` **(secret)**; `MAIL_FROM=LUDO <no-reply@ludo.de>`, `TECH_NOTIFY_EMAIL=technik@ludo.de` |
| Newsletter (un)subscribe | **Mauxy → Mautic** | **browser-direct** from the public site (+ bot-quiz) | `MAUXY_URL=https://mauxy.engage.wapsol.de`; publishable site key `MAUXY_KEY=ludo_5ad89d09ba4bff6118e0007e1a2683b5ba5b91360ed04b59` — in `web-ui/public/public/ludo-env.js` |
| Contact / email forms | **Email.js** | browser-direct | service `service_01zc3pa` · template `template_x7v725t` · public-key `jXwGkXBbqbOks2wJI` · forwarding `steam@simplify-erp.de` (all **publishable** by design) |

Notes:
- The **backend holds no Mauxy config** — Mauxy is browser-direct; its defenses are its CORS
  allow-list + the bot quiz + Mautic double-opt-in, not key secrecy (the key is publishable).
- Email.js details were previously only in the user's global `~/.claude/CLAUDE.md`; this is now their
  canonical home (cluster-specific, not a personal global preference).
- Brevo is the only secret here — rotate via the Brevo dashboard; set the real key in `.env.stag`/`.env.prod`.
