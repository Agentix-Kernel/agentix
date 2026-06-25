# CORS strategy

## Same-origin first (webapps)
The product frontends use a **same-origin** model: the portal is a `/portal` sub-path of the public
site and the API is proxied on the apex (`nginx` proxies `/api/`). So public + portal + API share one
origin → **no CORS needed**, shared session. Only **superadmin** keeps its own subdomain. The frontend
derives sibling-app URLs at runtime from the current host (`ludo-env.js`), per stage; dev uses the
loopback ports from [`network-and-ports.md`](network-and-ports.md).

## Gateway (explicit allow-list)
The gateway sets an explicit CORS allow-list (default `["http://10.0.99.1:8080"]`, env
`CORS_ORIGINS`) — **not** `*`, because credentials are allowed. Allowed headers are scoped
(`Authorization`, `Content-Type`, `Idempotency-Key`, `Last-Event-ID`).

## Post-cutover target
When the gateway becomes the public edge (B5), prefer the **same-origin** posture (nginx proxies
`/api/v1` to the gateway on the apex) so cross-origin CORS is needed only for the superadmin subdomain
and native clients (desktop/cli use bearer tokens, no browser CORS). Keep the allow-list explicit per
stage from `cluster.yaml:domains`.
