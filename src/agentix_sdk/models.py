"""Pydantic response models for the agentixd REST API.

These mirror the SQLite schema shape, not the kernel internals.
The SDK never imports from src/agentix — these are wire types only.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Session(BaseModel):
    id: str
    customer_id: str
    status: str
    started_at: str
    ended_at: str | None = None
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    app_meta: dict[str, Any] | None = None
    control_plane_id: str | None = None
    parent_session_id: str | None = None


class Turn(BaseModel):
    session_id: str
    turn_index: int
    role: str
    content: str | None = None
    tool_name: str | None = None
    tool_ok: bool | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int | None = None
    created_at: str | None = None
    status: str = "ok"


class DriverInfo(BaseModel):
    key: str
    tier: str
    type: str
    modality: str
    source: str
    extra: str
    sdk: str
    sdk_installed: bool


class AgentCardInfo(BaseModel):
    name: str
    description: str = ""
    version: str = "0"
    capabilities: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    activatable: bool = False


class ScaffoldFile(BaseModel):
    path: str
    content: str


class HealthStatus(BaseModel):
    status: str
    version: str
    kernel_ready: bool
