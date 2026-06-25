# Logging

Shared convention for the backend services.

- **`LOG_LEVEL`** — default `INFO`.
- **`LOG_FILE`** — empty ⇒ `<repo>/data/logs/app.log`; in k8s set an absolute PVC-backed path
  (e.g. `/app/data/logs/app.log`). Logs go to the file **and** stdout.
- Read in k8s: `kubectl -n ludo-<stage> exec -it deploy/<svc> -- tail -f /app/data/logs/app.log`.
- The agent uses `structlog` (structured logs); services should emit structured logs + correlation
  IDs where available. Observability target (OTel + Prometheus) is per the gateway design (§6).

These keys are in [`../templates/env.template`](../templates/env.template).
