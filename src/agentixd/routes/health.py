"""Health routes — /health/live and /health/ready."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import agentixd

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    """Liveness probe — always 200 while the process is running."""
    return {"status": "ok", "version": agentixd.__version__}


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness probe — 200 if kernel is fully initialized."""
    kernel = request.app.state.kernel
    if kernel.ready:
        return JSONResponse({"status": "ready", "version": agentixd.__version__, "kernel_ready": True})
    return JSONResponse(
        {"status": "starting", "kernel_ready": False, "error": kernel.error},
        status_code=503,
    )
