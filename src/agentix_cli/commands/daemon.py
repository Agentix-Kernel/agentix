"""daemon subcommands — install service unit, start/stop/status/logs."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from agentix_cli._config import load_config
from agentix_cli._output import error, ok, warn

app = typer.Typer(help="Manage the agentixd system service (systemd --user).")

_UNIT_NAME = "agentixd"
_USER_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"


def _unit_file() -> Path:
    return _USER_UNIT_DIR / f"{_UNIT_NAME}.service"


def _agentixd_bin() -> str:
    """Find the agentixd binary next to the running Python."""
    import sys

    candidate = Path(sys.executable).parent / "agentixd"
    if candidate.exists():
        return str(candidate)
    # Fallback: use python -m agentixd.main
    return f"{sys.executable} -m agentixd.main"


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


@app.command("install")
def daemon_install(
    config_path: Path | None = typer.Option(None, "--config", help="Config file path"),
    env_file: Path | None = typer.Option(None, "--env-file", help="EnvironmentFile for secrets"),
) -> None:
    """Write the agentixd.service unit file and reload systemd."""
    load_config(config_path)  # validate config exists / readable
    agentixd_bin = _agentixd_bin()
    env_line = f"EnvironmentFile={env_file}" if env_file else "# EnvironmentFile=/etc/agentixd/env"

    unit_content = f"""\
[Unit]
Description=Agentix kernel daemon
After=network.target

[Service]
Type=simple
ExecStart={agentixd_bin}
Restart=on-failure
RestartSec=5
{env_line}

[Install]
WantedBy=default.target
"""
    _USER_UNIT_DIR.mkdir(parents=True, exist_ok=True)
    _unit_file().write_text(unit_content)
    ok(f"Unit file written: {_unit_file()}")

    result = _systemctl("daemon-reload")
    if result.returncode == 0:
        ok("systemctl --user daemon-reload: OK")
    else:
        warn(f"daemon-reload failed: {result.stderr.strip()}")

    typer.echo("\nEnable and start with:")
    typer.echo(f"  systemctl --user enable --now {_UNIT_NAME}")


@app.command("start")
def daemon_start() -> None:
    """Start agentixd via systemctl --user."""
    r = _systemctl("start", _UNIT_NAME)
    if r.returncode == 0:
        ok(f"{_UNIT_NAME} started")
    else:
        error(f"start failed: {r.stderr.strip()}")
        raise typer.Exit(1)


@app.command("stop")
def daemon_stop() -> None:
    """Stop agentixd via systemctl --user."""
    r = _systemctl("stop", _UNIT_NAME)
    if r.returncode == 0:
        ok(f"{_UNIT_NAME} stopped")
    else:
        error(f"stop failed: {r.stderr.strip()}")
        raise typer.Exit(1)


@app.command("status")
def daemon_status() -> None:
    """Show agentixd service status."""
    r = _systemctl("status", _UNIT_NAME, "--no-pager", "--lines=20")
    typer.echo(r.stdout or r.stderr)


@app.command("logs")
def daemon_logs(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of log lines"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
) -> None:
    """Show agentixd logs via journalctl."""
    cmd = ["journalctl", "--user", "-u", _UNIT_NAME, f"-n{lines}", "--no-pager"]
    if follow:
        cmd.append("-f")
    subprocess.run(cmd)
