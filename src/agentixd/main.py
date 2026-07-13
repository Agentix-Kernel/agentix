"""agentixd — FastAPI app entry point.

Default transport: Unix Domain Socket at ~/.agentix/agentixd.sock.
TCP fallback: set AGENTIXD_HOST / AGENTIXD_PORT env vars or daemon.use_uds: false in config.
"""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

import agentixd
from agentixd._config import load_daemon_config
from agentixd._kernel import KernelState, build_kernel, teardown_kernel
from agentixd.routes import admin, health, scaffold, sessions

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the kernel on startup, tear it down on shutdown."""
    cfg_path = Path(os.environ.get("AGENTIXD_CONFIG", os.environ.get("AGENTIX_CONFIG", str(Path.home() / ".agentix" / "config.yaml"))))

    if not await asyncio.to_thread(cfg_path.exists):
        log.warning("config not found — admin/scaffold available; session execution disabled", path=str(cfg_path))
        app.state.kernel = KernelState(error=f"config not found: {cfg_path}")
    else:
        try:
            cfg = load_daemon_config(cfg_path)
            app.state.kernel = await build_kernel(cfg)
        except Exception as exc:
            log.error("kernel startup failed", error=str(exc))
            app.state.kernel = KernelState(error=str(exc))

    # Reload kernel on SIGHUP without restarting the process
    def _reload(signum: int, frame: object) -> None:
        log.info("SIGHUP received — kernel reload scheduled (not yet implemented)")

    signal.signal(signal.SIGHUP, _reload)

    yield

    await teardown_kernel(app.state.kernel)


def create_app() -> FastAPI:
    app = FastAPI(
        title="agentixd",
        description="Agentix kernel daemon — runtime + admin + scaffold",
        version=agentixd.__version__,
        lifespan=lifespan,
    )

    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(admin.router)
    app.include_router(scaffold.router)

    @app.exception_handler(Exception)
    async def _unhandled(request, exc):  # type: ignore[no-untyped-def]
        log.error("unhandled error", path=str(request.url), error=str(exc))
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    return app


app = create_app()


def run() -> None:
    """Console script entry point: agentixd."""
    from agentixd._config import _DEFAULT_SOCKET, load_daemon_config

    cfg_path = Path(os.environ.get("AGENTIXD_CONFIG", os.environ.get("AGENTIX_CONFIG", str(Path.home() / ".agentix" / "config.yaml"))))

    use_uds = True
    socket_path: Path = _DEFAULT_SOCKET
    host = os.environ.get("AGENTIXD_HOST", "10.0.99.1")
    port = int(os.environ.get("AGENTIXD_PORT", "7320"))

    if cfg_path.exists():
        try:
            cfg = load_daemon_config(cfg_path)
            use_uds = cfg.use_uds
            socket_path = cfg.socket_path
            host = cfg.host
            port = cfg.port
        except Exception:
            pass

    if use_uds:
        socket_path.parent.mkdir(parents=True, exist_ok=True)
        # Remove stale socket from a previous run
        if socket_path.exists():
            socket_path.unlink()
        log.info("starting agentixd", transport="uds", socket=str(socket_path), version=agentixd.__version__)
        uvicorn.run(
            "agentixd.main:app",
            uds=str(socket_path),
            log_level="info",
            access_log=True,
        )
        # Clean up socket file on exit
        if socket_path.exists():
            socket_path.unlink()
    else:
        log.info("starting agentixd", transport="tcp", host=host, port=port, version=agentixd.__version__)
        uvicorn.run(
            "agentixd.main:app",
            host=host,
            port=port,
            log_level="info",
            access_log=True,
        )
