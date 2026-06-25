# Tooling standards (Python services)

Applies to `ludo-agent`, `ludo-gateway`, `ludo-cli`. Canonical ruff config:
[`../templates/ruff.toml`](../templates/ruff.toml); baseline values in `cluster.yaml:tooling`.

| Concern | Standard |
|---|---|
| Python | **3.12** (`requires-python = ">=3.12"`; agent pins `<3.13`) |
| Package manager | **uv** (`uv sync`, `uv run`) |
| Ruff line-length | **120** (cluster standard; gateway moved 110→120 — widening adds no E501s) |
| Ruff target | `py312` |
| Ruff select — **core** (clients: gateway, cli) | `E, F, I, UP, B` + bugbear `extend-immutable-calls` for FastAPI DI |
| Ruff select — **engine** (agent) | core + `W, C4, SIM, RUF, ASYNC`, `ignore = E501` (autonomy-bar discipline) |
| mypy | **strict** for the engine (agent) + cli; lighter/absent for gateway today — standardize to strict (follow-up) |
| Tests | pytest; agent + gateway have `make`/CI (`ruff check . && pytest -q`); webapps tests run in isolated `tests/venv/` |
| Docker base | `python:3.12-slim` — see [`docker-baseline.md`](docker-baseline.md) |

**Two tiers, on purpose:** the agent is the autonomy engine and runs the stricter `engine` lint +
strict mypy; clients run `core`. Don't homogenize away the engine's extra rules.

To adopt: copy `templates/ruff.toml` into the repo's `pyproject.toml` `[tool.ruff]` (engine extends
`select`). Keep line-length 120 everywhere.
