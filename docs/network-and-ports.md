# Network & ports

Canonical values live in [`../constants/cluster.yaml`](../constants/cluster.yaml) (`network:` +
`broker:`). This doc explains them — it does not re-hardcode (change the YAML, not here).

## Loopback alias
House rule: address infra by the **loopback alias `10.0.99.1`**, never `localhost`/`127.0.0.1`.
Backends bind `0.0.0.0` inside containers; clients/config reach them via `10.0.99.1`.

## Port allocation (dev)
| Surface | Port | Repo |
|---|---|---|
| public web | 8080 | ludo-webapps |
| portal | 8080 `/portal` | ludo-webapps (same-origin sub-path) |
| superadmin | 8092 | ludo-webapps |
| apps backend | 8000 | ludo-webapps (retiring into gateway) |
| gateway edge | 8080 | ludo-gateway |
| NATS | 4222 | broker (private) |
| MinIO | 9000 | ludo-agent bulk store (private) |

> **Known collision:** public web and the gateway both target `8080` in dev. Resolve at gateway
> cutover (B5) — e.g. move the public dev server or the gateway to a distinct dev port.

## Broker (NATS JetStream)
URL `nats://10.0.99.1:4222` (env override `NATS_URL` / `LUDO_NATS_URL`). Subjects + streams are the
Contract B transport — see [`../contracts/`](../contracts/) and `broker:` in `cluster.yaml`:
`ludo.jobs` (+ `ludo.jobs.cancel`) on stream `LUDO_JOBS`; `ludo.events.<session_id>` on `LUDO_EVENTS`.
Only the **gateway** talks to NATS; clients never do.
