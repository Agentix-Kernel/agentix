"""AgentixClient — async HTTP client for agentixd.

No kernel imports. Apps install agentix[sdk] and talk to the daemon
instead of embedding the kernel directly.

Transport resolution order:
  1. AGENTIXD_SOCKET env → Unix Domain Socket
  2. base_url arg starting with "unix://" → Unix Domain Socket
  3. AGENTIXD_URL env → TCP URL
  4. ~/.agentix/agentixd.sock (if it exists) → Unix Domain Socket
  5. AGENTIXD_HOST:AGENTIXD_PORT → TCP
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

from agentix_sdk.models import AgentCardInfo, DriverInfo, ScaffoldFile, Session, Turn

_DEFAULT_SOCKET = Path.home() / ".agentix" / "agentixd.sock"


class AgentixError(Exception):
    """Raised when agentixd returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"agentixd {status_code}: {detail}")


class AgentixClient:
    """Async client for the agentixd kernel daemon.

    Usage::

        async with AgentixClient() as client:
            session = await client.create_session(customer_id="acme")
            turn = await client.run_turn(session.id, message="summarise report.csv")
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = None
        self._uds_path: str | None = None
        self._base: str = ""

        # Resolve transport
        socket_env = os.environ.get("AGENTIXD_SOCKET")

        if socket_env:
            self._uds_path = socket_env
            self._base = "http://agentixd"
        elif base_url and base_url.startswith("unix://"):
            self._uds_path = base_url[len("unix://"):]
            self._base = "http://agentixd"
        elif base_url:
            self._base = base_url.rstrip("/")
        elif os.environ.get("AGENTIXD_URL"):
            self._base = os.environ["AGENTIXD_URL"].rstrip("/")
        elif _DEFAULT_SOCKET.exists():
            self._uds_path = str(_DEFAULT_SOCKET)
            self._base = "http://agentixd"
        else:
            host = os.environ.get("AGENTIXD_HOST", "10.0.99.1")
            port = os.environ.get("AGENTIXD_PORT", "7320")
            self._base = f"http://{host}:{port}"

    async def __aenter__(self) -> AgentixClient:
        if self._uds_path:
            transport = httpx.AsyncHTTPTransport(uds=self._uds_path)
            self._http = httpx.AsyncClient(
                transport=transport, base_url=self._base, timeout=self._timeout
            )
        else:
            self._http = httpx.AsyncClient(base_url=self._base, timeout=self._timeout)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._http:
            await self._http.aclose()

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            raise RuntimeError("AgentixClient must be used as an async context manager")
        return self._http

    def _raise(self, r: httpx.Response) -> None:
        if r.is_error:
            try:
                detail = r.json().get("detail", r.text)
            except Exception:
                detail = r.text
            raise AgentixError(r.status_code, str(detail))

    # ── health ────────────────────────────────────────────────────────────────

    async def is_ready(self) -> bool:
        try:
            r = await self._client().get("/health/ready", timeout=2.0)
            return r.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False

    # ── sessions ──────────────────────────────────────────────────────────────

    async def create_session(
        self,
        customer_id: str,
        budget_usd: float | None = None,
        app_meta: dict[str, Any] | None = None,
        control_plane_id: str | None = None,
        parent_session_id: str | None = None,
    ) -> Session:
        body: dict[str, Any] = {"customer_id": customer_id}
        if budget_usd is not None:
            body["budget_usd"] = budget_usd
        if app_meta is not None:
            body["app_meta"] = app_meta
        if control_plane_id is not None:
            body["control_plane_id"] = control_plane_id
        if parent_session_id is not None:
            body["parent_session_id"] = parent_session_id
        r = await self._client().post("/run/sessions", json=body)
        self._raise(r)
        return Session.model_validate(r.json())

    async def run_turn(
        self,
        session_id: str,
        message: str | None = None,
    ) -> Turn:
        body: dict[str, Any] = {}
        if message is not None:
            body["message"] = message
        r = await self._client().post(f"/run/sessions/{session_id}/turn", json=body)
        self._raise(r)
        return Turn.model_validate(r.json())

    async def get_session(self, session_id: str) -> Session:
        r = await self._client().get(f"/run/sessions/{session_id}")
        self._raise(r)
        return Session.model_validate(r.json())

    async def list_sessions(
        self,
        customer_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Session]:
        params: dict[str, Any] = {"limit": limit}
        if customer_id:
            params["customer_id"] = customer_id
        if status:
            params["status"] = status
        r = await self._client().get("/run/sessions", params=params)
        self._raise(r)
        return [Session.model_validate(s) for s in r.json()]

    async def list_turns(self, session_id: str) -> list[Turn]:
        r = await self._client().get(f"/run/sessions/{session_id}/turns")
        self._raise(r)
        return [Turn.model_validate(t) for t in r.json()]

    # ── admin: drivers ────────────────────────────────────────────────────────

    async def list_drivers(self) -> list[DriverInfo]:
        r = await self._client().get("/admin/drivers")
        self._raise(r)
        return [DriverInfo.model_validate(d) for d in r.json()]

    async def install_driver(
        self,
        key: str,
        name: str | None = None,
        model: str | None = None,
        api_key_env: str | None = None,
        base_url: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"key": key, "dry_run": dry_run}
        if name:
            body["name"] = name
        if model:
            body["model"] = model
        if api_key_env:
            body["api_key_env"] = api_key_env
        if base_url:
            body["base_url"] = base_url
        r = await self._client().post("/admin/drivers", json=body)
        self._raise(r)
        return r.json()

    async def uninstall_driver(self, name: str, dry_run: bool = False) -> dict[str, Any]:
        r = await self._client().delete(f"/admin/drivers/{name}", params={"dry_run": dry_run})
        self._raise(r)
        return r.json()

    # ── admin: agents ─────────────────────────────────────────────────────────

    async def list_agents(self) -> list[AgentCardInfo]:
        r = await self._client().get("/admin/agents")
        self._raise(r)
        return [AgentCardInfo.model_validate(a) for a in r.json()]

    async def register_agent(self, card: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
        r = await self._client().post("/admin/agents", json={**card, "dry_run": dry_run})
        self._raise(r)
        return r.json()

    async def unregister_agent(self, name: str, dry_run: bool = False) -> dict[str, Any]:
        r = await self._client().delete(f"/admin/agents/{name}", params={"dry_run": dry_run})
        self._raise(r)
        return r.json()

    # ── admin: scaffold ───────────────────────────────────────────────────────

    async def scaffold_driver(
        self,
        name: str,
        modality: str = "chat",
        description: str = "",
    ) -> ScaffoldFile:
        r = await self._client().post(
            "/admin/scaffold/driver",
            json={"name": name, "modality": modality, "description": description},
        )
        self._raise(r)
        return ScaffoldFile.model_validate(r.json())

    async def scaffold_agent(
        self,
        name: str,
        description: str = "",
    ) -> list[ScaffoldFile]:
        r = await self._client().post(
            "/admin/scaffold/agent",
            json={"name": name, "description": description},
        )
        self._raise(r)
        return [ScaffoldFile.model_validate(f) for f in r.json()]
