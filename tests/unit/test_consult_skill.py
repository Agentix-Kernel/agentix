"""ConsultSkill — single-root and multi-root SKILL.md lookup tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agentix.skills.consult_skill import ConsultSkill, ConsultSkillInput


def _skill_md(root: Path, name: str, body: str = "# procedure") -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    fm = f"---\nname: {name}\ndescription: desc\n---\n"
    (d / "SKILL.md").write_text(fm + body, encoding="utf-8")


def _ctx(skills_root):
    ctx = MagicMock()
    ctx.skills_root = skills_root
    return ctx


tool = ConsultSkill()


def _call(ctx, name: str):
    inp = ConsultSkillInput(name=name)
    return asyncio.get_event_loop().run_until_complete(tool.call(inp, ctx))


# ── single root ───────────────────────────────────────────────────────────────


def test_reads_skill_md_single_root(tmp_path: Path) -> None:
    _skill_md(tmp_path, "extract", body="# Extract")
    result = _call(_ctx(str(tmp_path)), "extract")
    assert result.name == "extract"
    assert "# Extract" in result.content
    assert result.truncated is False


def test_unknown_skill_raises(tmp_path: Path) -> None:
    _skill_md(tmp_path, "existing")
    with pytest.raises(ValueError, match="no skill named"):
        _call(_ctx(str(tmp_path)), "ghost")


# ── multi-root ────────────────────────────────────────────────────────────────


def test_consult_skill_across_roots(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    _skill_md(root_a, "skill-a", body="# A procedure")
    _skill_md(root_b, "skill-b", body="# B procedure")

    result_a = _call(_ctx([str(root_a), str(root_b)]), "skill-a")
    result_b = _call(_ctx([str(root_a), str(root_b)]), "skill-b")
    assert "# A procedure" in result_a.content
    assert "# B procedure" in result_b.content


def test_consult_skill_first_root_wins(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    _skill_md(root_a, "shared", body="# from A")
    _skill_md(root_b, "shared", body="# from B")

    result = _call(_ctx([str(root_a), str(root_b)]), "shared")
    assert "# from A" in result.content
