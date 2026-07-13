"""driver subcommands — list, show, install, uninstall."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Annotated

import typer

from agentix_cli._config import CliDriverSpec, load_config, save_config, write_config
from agentix_cli._output import dry_run_header, error, make_table, ok, print_table, warn, would

app = typer.Typer(help="Manage drivers (list, show, install, uninstall).")

# ── driver metadata catalogue ──────────────────────────────────────────────

_DRIVER_META: dict[str, dict[str, str]] = {
    # vendor — require opt-in extra
    "anthropic": {"type": "model", "modality": "chat", "source": "api", "extra": "anthropic", "sdk": "anthropic"},
    "openai": {"type": "model", "modality": "chat", "source": "api", "extra": "openai", "sdk": "openai"},
    "gemini": {"type": "model", "modality": "chat", "source": "api", "extra": "openai", "sdk": "openai"},
    "groq": {"type": "model", "modality": "chat", "source": "api", "extra": "groq", "sdk": "groq"},
    "ollama": {"type": "model", "modality": "chat", "source": "local", "extra": "openai", "sdk": "openai"},
    "grok": {"type": "model", "modality": "chat", "source": "api", "extra": "openai", "sdk": "openai"},
    "nvidia": {"type": "model", "modality": "chat", "source": "api", "extra": "openai", "sdk": "openai"},
    "melious": {"type": "model", "modality": "chat", "source": "api", "extra": "openai", "sdk": "openai"},
    "openai-embedding": {"type": "model", "modality": "embedding", "source": "api", "extra": "openai", "sdk": "openai"},
    # intrinsic — ship with kernel
    "huble": {"type": "model", "modality": "chat", "source": "gateway", "extra": "", "sdk": ""},
    "huble-embedding": {"type": "model", "modality": "embedding", "source": "gateway", "extra": "", "sdk": ""},
    "hf-stt": {"type": "model", "modality": "stt", "source": "api", "extra": "hf", "sdk": "huggingface_hub"},
    "minio-object-store": {
        "type": "storage",
        "modality": "object",
        "source": "local",
        "extra": "minio",
        "sdk": "minio",
    },
    "postgresql-relational": {
        "type": "storage",
        "modality": "relational",
        "source": "local",
        "extra": "postgresql",
        "sdk": "asyncpg",
    },
    "local-object-store": {"type": "storage", "modality": "object", "source": "local", "extra": "", "sdk": ""},
    "sqlite-relational": {"type": "storage", "modality": "relational", "source": "local", "extra": "", "sdk": ""},
    "local-file-store": {"type": "storage", "modality": "file", "source": "local", "extra": "", "sdk": ""},
}

_VENDOR_KEYS = {k for k, v in _DRIVER_META.items() if v["extra"] in ("anthropic", "openai", "groq")}


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
    extra = meta.get("extra", "")
    if extra in ("anthropic", "openai", "groq"):
        return "vendor"
    return "intrinsic"


@app.command("list")
def driver_list() -> None:
    """List all available drivers with type, modality, and SDK status."""
    t = make_table("Key", "Tier", "Type", "Modality", "Source", "Extra", "SDK installed")
    for key, meta in sorted(_DRIVER_META.items()):
        sdk = meta["sdk"]
        installed = "[green]yes[/green]" if _sdk_installed(sdk) else "[red]no[/red]"
        tier_label = "[yellow]vendor[/yellow]" if _tier(key) == "vendor" else "intrinsic"
        extra_label = f"agentix[{meta['extra']}]" if meta["extra"] else "[dim]core[/dim]"
        t.add_row(key, tier_label, meta["type"], meta["modality"], meta["source"], extra_label, installed)
    print_table(t)


@app.command("show")
def driver_show(key: str = typer.Argument(..., help="Driver key (e.g. anthropic, sqlite-relational)")) -> None:
    """Show details for a single driver."""
    if key not in _DRIVER_META:
        error(f"unknown driver key {key!r}. Run 'agentix driver list' to see all available drivers.")
        raise typer.Exit(1)
    meta = _DRIVER_META[key]
    sdk = meta["sdk"]
    from agentix_cli._output import print_kv

    print_kv(
        [
            ("Key", key),
            ("Tier", _tier(key)),
            ("Type", meta["type"]),
            ("Modality", meta["modality"]),
            ("Source", meta["source"]),
            ("Install extra", f"pip install agentix[{meta['extra']}]" if meta["extra"] else "(ships with kernel)"),
            ("SDK package", sdk or "(none)"),
            ("SDK installed", "yes" if _sdk_installed(sdk) else "no"),
        ],
        title=f"Driver: {key}",
    )


@app.command("install")
def driver_install(
    key: str = typer.Argument(..., help="Driver key to install (e.g. anthropic)"),
    name: str = typer.Option("", help="DriverSpec name in config (defaults to driver key)"),
    model: str | None = typer.Option(None, help="Default model for this driver"),
    api_key_env: str | None = typer.Option(None, help="Env var holding the API key"),
    base_url: str | None = typer.Option(None, help="Override base URL"),
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Preview changes without applying")] = False,
    config_path: Path | None = typer.Option(None, "--config", help="Config file path"),
) -> None:
    """Install a driver: pip-install its SDK extra and register it in config."""
    if key not in _DRIVER_META:
        error(f"unknown driver key {key!r}. Run 'agentix driver list'.")
        raise typer.Exit(1)

    meta = _DRIVER_META[key]
    spec_name = name or key
    extra = meta["extra"]
    sdk = meta["sdk"]
    cfg = load_config(config_path)

    if dry_run:
        dry_run_header()
        if extra:
            would(f"pip install agentix[{extra}]  (SDK: {sdk})")
        else:
            would("no SDK install needed (intrinsic driver)")
        would(f"add DriverSpec name={spec_name!r} driver={key!r} to {cfg.config_path}")
        return

    # 1. Install SDK extra if needed
    if extra and not _sdk_installed(sdk):
        typer.echo(f"Installing agentix[{extra}]...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", f"agentix[{extra}]"],
            capture_output=False,
        )
        if result.returncode != 0:
            error(f"pip install failed (exit {result.returncode})")
            raise typer.Exit(result.returncode)
    elif extra:
        ok(f"SDK {sdk!r} already installed")

    # 2. Register in config
    driver_spec = CliDriverSpec(
        name=spec_name,
        driver=key,
        type=meta["type"],
        modality=meta["modality"],
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
    )
    raw = save_config(cfg, driver_to_add=driver_spec)
    write_config(raw, cfg.config_path)
    ok(f"Driver {key!r} registered as {spec_name!r} in {cfg.config_path}")
    if _tier(key) == "vendor":
        warn("Remember to set your API key — see docs/vendor-licenses.md for ToS.")


@app.command("uninstall")
def driver_uninstall(
    name: str = typer.Argument(..., help="DriverSpec name in config to remove"),
    dry_run: Annotated[bool, typer.Option("--dry-run", "-n", help="Preview changes without applying")] = False,
    config_path: Path | None = typer.Option(None, "--config", help="Config file path"),
) -> None:
    """Remove a driver from config (does not uninstall the SDK package)."""
    cfg = load_config(config_path)

    match = next((d for d in cfg.drivers if d.name == name), None)
    if match is None:
        error(f"no driver named {name!r} found in {cfg.config_path}")
        raise typer.Exit(1)

    if dry_run:
        dry_run_header()
        would(f"remove DriverSpec name={name!r} driver={match.driver!r} from {cfg.config_path}")
        warn("SDK package is NOT uninstalled (it may be used by other drivers)")
        return

    raw = save_config(cfg, driver_name_to_remove=name)
    write_config(raw, cfg.config_path)
    ok(f"Driver {name!r} removed from {cfg.config_path}")
    warn("SDK package was not uninstalled — run 'pip uninstall <sdk>' manually if needed.")
