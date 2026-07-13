"""Admin routes — /admin/drivers, /admin/agents, /admin/config."""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# ── Driver metadata (mirrors CLI catalogue) ───────────────────────────────────

_DRIVER_META: dict[str, dict[str, str]] = {
    "anthropic":             {"type": "model",   "modality": "chat",       "source": "api",     "extra": "anthropic", "sdk": "anthropic"},
    "openai":                {"type": "model",   "modality": "chat",       "source": "api",     "extra": "openai",    "sdk": "openai"},
    "gemini":                {"type": "model",   "modality": "chat",       "source": "api",     "extra": "openai",    "sdk": "openai"},
    "groq":                  {"type": "model",   "modality": "chat",       "source": "api",     "extra": "groq",      "sdk": "groq"},
    "ollama":                {"type": "model",   "modality": "chat",       "source": "local",   "extra": "openai",    "sdk": "openai"},
    "grok":                  {"type": "model",   "modality": "chat",       "source": "api",     "extra": "openai",    "sdk": "openai"},
    "nvidia":                {"type": "model",   "modality": "chat",       "source": "api",     "extra": "openai",    "sdk": "openai"},
    "melious":               {"type": "model",   "modality": "chat",       "source": "api",     "extra": "openai",    "sdk": "openai"},
    "openai-embedding":      {"type": "model",   "modality": "embedding",  "source": "api",     "extra": "openai",    "sdk": "openai"},
    "huble":                 {"type": "model",   "modality": "chat",       "source": "gateway", "extra": "",          "sdk": ""},
    "huble-embedding":       {"type": "model",   "modality": "embedding",  "source": "gateway", "extra": "",          "sdk": ""},
    "hf-stt":                {"type": "model",   "modality": "stt",        "source": "api",     "extra": "hf",        "sdk": "huggingface_hub"},
    "minio-object-store":    {"type": "storage", "modality": "object",     "source": "local",   "extra": "minio",     "sdk": "minio"},
    "postgresql-relational": {"type": "storage", "modality": "relational", "source": "local",   "extra": "postgresql","sdk": "asyncpg"},
    "local-object-store":    {"type": "storage", "modality": "object",     "source": "local",   "extra": "",          "sdk": ""},
    "sqlite-relational":     {"type": "storage", "modality": "relational", "source": "local",   "extra": "",          "sdk": ""},
    "local-file-store":      {"type": "storage", "modality": "file",       "source": "local",   "extra": "",          "sdk": ""},
}


def _sdk_installed(sdk: str) -> bool:
    if not sdk:
        return True
    try:
        __import__(sdk.replace("-", "_"))
        return True
    except ImportError:
        return False


def _tier(key: str) -> str:
    meta = _DRIVER_META.get(key, {})
    return "vendor" if meta.get("extra") in ("anthropic", "openai", "groq") else "intrinsic"


def _driver_info(key: str) -> dict[str, Any]:
    meta = _DRIVER_META.get(key, {})
    return {
        "key": key,
        "tier": _tier(key),
        "type": meta.get("type", ""),
        "modality": meta.get("modality", ""),
        "source": meta.get("source", ""),
        "extra": f"agentix[{meta['extra']}]" if meta.get("extra") else "core",
        "sdk": meta.get("sdk", ""),
        "sdk_installed": _sdk_installed(meta.get("sdk", "")),
    }


def _load_config_raw(cfg_path: Path) -> dict[str, Any]:
    import yaml  # type: ignore[import-untyped]
    return yaml.safe_load(cfg_path.read_text()) or {} if cfg_path.exists() else {}


def _save_config_raw(raw: dict[str, Any], cfg_path: Path) -> None:
    import yaml  # type: ignore[import-untyped]
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.dump(raw, default_flow_style=False, sort_keys=False))


def _agents_file(cfg_path: Path) -> Path:
    return cfg_path.parent / "agents.json"


def _load_agents(agents_file: Path) -> list[dict[str, Any]]:
    if not agents_file.exists():
        return []
    try:
        return json.loads(agents_file.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_agents(agents_file: Path, agents: list[dict[str, Any]]) -> None:
    agents_file.parent.mkdir(parents=True, exist_ok=True)
    agents_file.write_text(json.dumps(agents, indent=2))


# ── Driver endpoints ──────────────────────────────────────────────────────────

@router.get("/drivers")
async def list_drivers() -> list[dict[str, Any]]:
    """List all known driver keys with tier, modality, and SDK status."""
    return [_driver_info(k) for k in sorted(_DRIVER_META)]


@router.get("/drivers/{key}")
async def show_driver(key: str) -> dict[str, Any]:
    """Show details for one driver."""
    if key not in _DRIVER_META:
        raise HTTPException(status_code=404, detail=f"unknown driver key {key!r}")
    return _driver_info(key)


class InstallDriverRequest(BaseModel):
    key: str
    name: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    dry_run: bool = False


@router.post("/drivers", status_code=201)
async def install_driver(body: InstallDriverRequest, request: Request) -> dict[str, Any]:
    """Install a driver: pip-install its SDK extra and register it in config."""
    if body.key not in _DRIVER_META:
        raise HTTPException(status_code=422, detail=f"unknown driver key {body.key!r}")

    meta = _DRIVER_META[body.key]
    sdk = meta["sdk"]
    extra = meta["extra"]
    spec_name = body.name or body.key
    cfg_path = request.app.state.kernel._cfg.config_path

    actions: list[str] = []

    if extra and not _sdk_installed(sdk):
        actions.append(f"pip install agentix[{extra}]  (SDK: {sdk})")
    else:
        actions.append(f"SDK {sdk!r} already installed — skipping pip")

    entry: dict[str, Any] = {
        "name": spec_name, "driver": body.key,
        "type": meta["type"], "modality": meta["modality"],
    }
    if body.model:
        entry["model"] = body.model
    if body.api_key_env:
        entry["api_key_env"] = body.api_key_env
    if body.base_url:
        entry["base_url"] = body.base_url
    actions.append(f"register DriverSpec name={spec_name!r} driver={body.key!r} in {cfg_path}")

    if body.dry_run:
        return {"dry_run": True, "actions": actions}

    # Run pip install if needed (off-thread to keep the event loop unblocked)
    if extra and not _sdk_installed(sdk):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "pip", "install", f"agentix[{extra}]"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"pip install failed: {result.stderr}")

    # Update config YAML
    raw = _load_config_raw(cfg_path)
    drivers = raw.get("drivers", [])
    drivers = [d for d in drivers if d.get("name") != spec_name]
    drivers.append(entry)
    raw["drivers"] = drivers
    _save_config_raw(raw, cfg_path)

    log.info("driver installed", key=body.key, name=spec_name)
    return {"installed": True, "name": spec_name, "driver": body.key, "config": str(cfg_path)}


@router.delete("/drivers/{name}")
async def uninstall_driver(
    name: str,
    request: Request,
    dry_run: bool = Query(False),
) -> dict[str, Any]:
    """Remove a driver spec from config (does not uninstall the SDK package)."""
    cfg_path = request.app.state.kernel._cfg.config_path
    raw = _load_config_raw(cfg_path)
    drivers = raw.get("drivers", [])
    match = next((d for d in drivers if d.get("name") == name), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"no driver named {name!r} in config")

    if dry_run:
        return {"dry_run": True, "actions": [f"remove driver {name!r} from {cfg_path}"]}

    raw["drivers"] = [d for d in drivers if d.get("name") != name]
    _save_config_raw(raw, cfg_path)
    log.info("driver removed", name=name)
    return {"removed": True, "name": name, "note": "SDK package was not uninstalled"}


# ── Agent endpoints ───────────────────────────────────────────────────────────

@router.get("/agents")
async def list_agents(request: Request) -> list[dict[str, Any]]:
    """List registered A2A agent cards."""
    af = _agents_file(request.app.state.kernel._cfg.config_path)
    return _load_agents(af)


@router.get("/agents/{name}")
async def show_agent(name: str, request: Request) -> dict[str, Any]:
    """Show one agent card by name."""
    af = _agents_file(request.app.state.kernel._cfg.config_path)
    match = next((a for a in _load_agents(af) if a.get("name") == name), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"agent {name!r} not found")
    return match


class RegisterAgentRequest(BaseModel):
    name: str
    description: str = ""
    version: str = "0"
    activatable: bool = False
    skills: list[dict[str, Any]] = []
    tools: list[str] = []
    dry_run: bool = False


@router.post("/agents", status_code=201)
async def register_agent(body: RegisterAgentRequest, request: Request) -> dict[str, Any]:
    """Register an A2A agent card."""
    from agentix.a2a.card import AgentCard, AgentSkill

    try:
        skill_list = [AgentSkill(**s) for s in body.skills]
        card = AgentCard(
            name=body.name, description=body.description,
            version=body.version, activatable=body.activatable,
            skills=skill_list, tools=body.tools,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    af = _agents_file(request.app.state.kernel._cfg.config_path)

    if body.dry_run:
        return {"dry_run": True, "actions": [f"register agent {body.name!r} in {af}"]}

    agents = _load_agents(af)
    agents = [a for a in agents if a.get("name") != body.name]
    agents.append(card.model_dump())
    _save_agents(af, agents)
    log.info("agent registered", name=body.name)
    return {"registered": True, "name": body.name, "file": str(af)}


@router.delete("/agents/{name}")
async def unregister_agent(
    name: str,
    request: Request,
    dry_run: bool = Query(False),
) -> dict[str, Any]:
    """Remove an A2A agent card."""
    af = _agents_file(request.app.state.kernel._cfg.config_path)
    agents = _load_agents(af)
    match = next((a for a in agents if a.get("name") == name), None)
    if match is None:
        raise HTTPException(status_code=404, detail=f"agent {name!r} not found")

    if dry_run:
        return {"dry_run": True, "actions": [f"remove agent {name!r} from {af}"]}

    agents = [a for a in agents if a.get("name") != name]
    _save_agents(af, agents)
    log.info("agent unregistered", name=name)
    return {"removed": True, "name": name}


# ── Config endpoints ──────────────────────────────────────────────────────────

@router.get("/config")
async def show_config(request: Request) -> dict[str, Any]:
    """Return resolved daemon config (secrets redacted)."""
    cfg = request.app.state.kernel._cfg
    if cfg is None:
        raise HTTPException(status_code=503, detail="daemon config not loaded")
    return {
        "config_path": str(cfg.config_path),
        "sqlite_path": str(cfg.sqlite_path),
        "memory_path": str(cfg.memory_path),
        "minio_configured": cfg.has_minio,
        "minio_endpoint": cfg.minio_endpoint or None,
        "minio_bucket": cfg.minio_bucket,
        "budget_usd": cfg.budget_usd,
        "host": cfg.host,
        "port": cfg.port,
        "drivers": cfg.driver_specs,
    }


@router.post("/config/validate")
async def validate_config(request: Request) -> dict[str, Any]:
    """Validate config and driver SDK installs. Returns list of issues."""
    kernel = request.app.state.kernel
    cfg = kernel._cfg
    issues: list[str] = []
    warnings: list[str] = []

    if not cfg.config_path.exists():
        issues.append(f"Config file not found: {cfg.config_path}")

    if not cfg.has_drivers:
        warnings.append("No drivers declared — session execution disabled")

    if not cfg.has_minio:
        warnings.append("MinIO not configured — using local-fs checkpoints (dev mode)")

    for d in cfg.driver_specs:
        key = d.get("driver", "")
        if key not in _DRIVER_META:
            issues.append(f"Driver {d.get('name')!r}: unknown key {key!r}")
            continue
        meta = _DRIVER_META[key]
        sdk = meta.get("sdk", "")
        if sdk and not _sdk_installed(sdk):
            issues.append(f"Driver {d.get('name')!r}: SDK {sdk!r} not installed — run 'agentix driver install {key}'")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "kernel_ready": kernel.ready,
    }
