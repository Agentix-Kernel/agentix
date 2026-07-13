"""Daemon config loader — reads ~/.agentix/config.yaml into DaemonConfig.

Decoupled from CliConfig: the daemon needs a full KernelConfig (storage paths,
driver specs, optional MinIO), plus daemon-specific host/port settings.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_DEFAULT_CONFIG = Path.home() / ".agentix" / "config.yaml"


@dataclass
class DaemonConfig:
    sqlite_path: Path
    memory_path: Path
    minio_endpoint: str | None = None
    minio_access_key: str | None = None
    minio_secret_key: str | None = None
    minio_bucket: str = "agentix"
    driver_specs: list[dict[str, Any]] = field(default_factory=list)
    budget_usd: float = 200.0
    host: str = "10.0.99.1"
    port: int = 7320
    config_path: Path = field(default_factory=lambda: _DEFAULT_CONFIG)

    @property
    def has_minio(self) -> bool:
        return bool(self.minio_endpoint and self.minio_access_key and self.minio_secret_key)

    @property
    def has_drivers(self) -> bool:
        return bool(self.driver_specs)


def load_daemon_config(path: Path | None = None) -> DaemonConfig:
    """Load and parse config YAML into DaemonConfig. Raises if file is absent."""
    resolved = path or Path(
        os.environ.get("AGENTIXD_CONFIG", os.environ.get("AGENTIX_CONFIG", str(_DEFAULT_CONFIG)))
    )

    import yaml  # type: ignore[import-untyped]

    raw: dict[str, Any] = yaml.safe_load(resolved.read_text()) or {}

    def _path(key: str, default: str | None = None) -> Path:
        v = raw.get(key, default)
        if not v:
            raise ValueError(f"Config key '{key}' is required in {resolved}")
        return Path(str(v)).expanduser()

    minio_block: dict[str, Any] = raw.get("minio", {})
    daemon_block: dict[str, Any] = raw.get("daemon", {})

    return DaemonConfig(
        sqlite_path=_path("sqlite_path", "~/.agentix/kernel.db"),
        memory_path=_path("memory_path", "~/.agentix/memory"),
        minio_endpoint=minio_block.get("endpoint") or os.environ.get("MINIO_ENDPOINT"),
        minio_access_key=minio_block.get("access_key") or os.environ.get("MINIO_ACCESS_KEY"),
        minio_secret_key=minio_block.get("secret_key") or os.environ.get("MINIO_SECRET_KEY"),
        minio_bucket=minio_block.get("bucket", "agentix"),
        driver_specs=raw.get("drivers", []),
        budget_usd=float(raw.get("budget_usd", 200.0)),
        host=os.environ.get("AGENTIXD_HOST", daemon_block.get("host", "10.0.99.1")),
        port=int(os.environ.get("AGENTIXD_PORT", daemon_block.get("port", 7320))),
        config_path=resolved,
    )
