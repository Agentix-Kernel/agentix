"""Skills loader emits one aggregate summary (loaded + failed) at startup."""

from __future__ import annotations

import json
from pathlib import Path

from structlog.testing import capture_logs

from agentix.skills.loader import load_skills
from agentix.tools.registry import ToolRegistry


def _bundle(root: Path, name: str, *, manifest: str) -> None:
    d = root / name
    d.mkdir()
    (d / "manifest.json").write_text(manifest, encoding="utf-8")


def test_summary_lists_loaded_and_failed(tmp_path: Path) -> None:
    # One valid doctrine-only skill (no tools) + one broken manifest.
    _bundle(tmp_path, "good", manifest=json.dumps({"name": "good", "version": "1", "trigger": {}}))
    _bundle(tmp_path, "broken", manifest="{not json}")

    reg = ToolRegistry()
    with capture_logs() as logs:
        loaded = load_skills(tmp_path, reg)

    assert [m["name"] for m in loaded] == ["good"]
    summaries = [e for e in logs if e.get("event") == "skills.load_summary"]
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["loaded"] == ["good"]
    assert summary["loaded_count"] == 1
    assert summary["failed"] == ["broken"]
    assert summary["failed_count"] == 1
