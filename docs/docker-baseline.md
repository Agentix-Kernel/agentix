# Docker baseline

Conventions for the containerized Python services (agent, gateway; webapps backend is retiring).

- **Base image:** `python:3.12-slim` (`cluster.yaml:tooling.docker_base`).
- **Non-root:** run as a dedicated unprivileged user (the agent uses `uid 10000`, group `ludo`,
  home `/home/ludo`). Adopt the same for the gateway image (dev stages may run root; prod should not).
- **Deps:** install via `uv` (`uv sync`/`uv pip install`); `PYTHONDONTWRITEBYTECODE=1`,
  `PYTHONUNBUFFERED=1`. Don't bake source as a volume in prod — build into the image.
- **node_modules / venv stay out of images** (house rule) — built/mounted, not committed.
- **One concern per container:** agent = `app` + `minio`; gateway = `gateway` + `nats`; each store
  is its own container, never shared (three-stores rule). DB volumes:
  gateway `/srv/data`, agent `/data` + `/app/memory`, webapps `/app/data/sqlite`.
- **Stateful caveat:** single-writer SQLite (ADR 0001) → one writer replica owns the data volume;
  scale reads with stateless replicas. See [`db-conventions.md`](db-conventions.md).

Ports + addressing: [`network-and-ports.md`](network-and-ports.md). Build commands stay per-repo
(the user runs Docker builds on CLI).
