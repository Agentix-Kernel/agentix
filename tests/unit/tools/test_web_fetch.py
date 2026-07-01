from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentix.tools.spike.web_fetch import WebFetch, WebFetchInput


class _Response:
    def __init__(self, status: int, body: str = "", content_type: str = "text/plain") -> None:
        self.status_code = status
        self.text = body
        self.headers = {"content-type": content_type}


class _StubClient:
    def __init__(self, response: _Response) -> None:
        self._response = response

    async def __aenter__(self) -> _StubClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        return None

    async def get(self, _url: str) -> _Response:
        return self._response


def _patch(monkeypatch: pytest.MonkeyPatch, response: _Response) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **kw: _StubClient(response))


@pytest.mark.asyncio
async def test_web_fetch_raises_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _Response(404, "404: Not Found"))
    tool = WebFetch()
    with pytest.raises(ValueError, match="HTTP 404"):
        await tool.call(
            WebFetchInput(url="https://raw.githubusercontent.com/odoo/odoo/18.0/missing.py"),
            ctx=None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_web_fetch_raises_on_500(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _Response(500, "Server Error"))
    tool = WebFetch()
    with pytest.raises(ValueError, match="HTTP 500"):
        await tool.call(
            WebFetchInput(url="https://github.com/odoo/odoo"),
            ctx=None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_web_fetch_returns_body_on_200(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, _Response(200, "ok body", content_type="text/x-python"))
    tool = WebFetch()
    out = await tool.call(
        WebFetchInput(url="https://raw.githubusercontent.com/odoo/odoo/18.0/x.py"),
        ctx=None,  # type: ignore[arg-type]
    )
    assert out.status == 200  # type: ignore[attr-defined]
    assert out.body == "ok body"  # type: ignore[attr-defined]
