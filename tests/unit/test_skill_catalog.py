"""SkillCatalog — multi-root discovery and AgentSkill projection tests."""

from __future__ import annotations

from pathlib import Path

from agentix.skills.catalog import SkillCatalog


def _skill_md(root: Path, name: str, *, frontmatter: str = "", body: str = "# body") -> None:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    content = f"---\n{frontmatter}\n---\n{body}" if frontmatter else body
    (d / "SKILL.md").write_text(content, encoding="utf-8")


# ── single-root (existing behaviour) ─────────────────────────────────────────


def test_single_root_str(tmp_path: Path) -> None:
    _skill_md(tmp_path, "alpha", frontmatter="name: alpha\ndescription: Alpha skill")
    cat = SkillCatalog(str(tmp_path))
    bundles = cat.bundles()
    assert len(bundles) == 1
    assert bundles[0].name == "alpha"


def test_single_root_path(tmp_path: Path) -> None:
    _skill_md(tmp_path, "beta")
    cat = SkillCatalog(tmp_path)
    assert len(cat.bundles()) == 1


def test_missing_root_returns_empty(tmp_path: Path) -> None:
    cat = SkillCatalog(tmp_path / "nonexistent")
    assert cat.bundles() == []


# ── multi-root ────────────────────────────────────────────────────────────────


def test_multi_root_merges_bundles(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    _skill_md(root_a, "skill-a", frontmatter="name: skill-a\ndescription: from A")
    _skill_md(root_b, "skill-b", frontmatter="name: skill-b\ndescription: from B")

    cat = SkillCatalog([root_a, root_b])
    names = {b.name for b in cat.bundles()}
    assert names == {"skill-a", "skill-b"}


def test_multi_root_first_root_wins_on_clash(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    _skill_md(root_a, "shared", frontmatter="name: shared\ndescription: from A")
    _skill_md(root_b, "shared", frontmatter="name: shared\ndescription: from B")

    from structlog.testing import capture_logs

    with capture_logs() as logs:
        cat = SkillCatalog([root_a, root_b])
        bundles = cat.bundles()

    assert len(bundles) == 1
    assert bundles[0].description == "from A"
    assert any(e.get("event") == "skills.name_clash" for e in logs)


def test_multi_root_missing_root_skipped(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_a.mkdir()
    _skill_md(root_a, "real")
    cat = SkillCatalog([root_a, tmp_path / "ghost"])
    assert len(cat.bundles()) == 1


def test_multi_root_legacy_root_property(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    cat = SkillCatalog([root_a, root_b])
    assert cat.root == root_a


# ── A2A frontmatter parsing ───────────────────────────────────────────────────


def test_a2a_frontmatter_parsed(tmp_path: Path) -> None:
    fm = (
        "id: analyse-schema\n"
        "name: Analyse Schema\n"
        "description: introspect\n"
        "tags:\n  - odoo\n  - schema\n"
        "examples:\n  - describe res.partner\n"
        "input_modes:\n  - application/json\n"
        "output_modes:\n  - application/json\n  - text/plain\n"
    )
    _skill_md(tmp_path, "analyse-schema", frontmatter=fm)
    cat = SkillCatalog(tmp_path)
    b = cat.bundles()[0]
    assert b.id == "analyse-schema"
    assert b.tags == ("odoo", "schema")
    assert b.examples == ("describe res.partner",)
    assert b.input_modes == ("application/json",)
    assert b.output_modes == ("application/json", "text/plain")


def test_to_agent_skill(tmp_path: Path) -> None:
    fm = (
        "id: my-skill\n"
        "name: My Skill\n"
        "description: does stuff\n"
        "tags:\n  - foo\n"
        "input_modes:\n  - text/plain\n"
        "output_modes:\n  - application/json\n"
    )
    _skill_md(tmp_path, "my-skill", frontmatter=fm)
    bundle = SkillCatalog(tmp_path).bundles()[0]
    skill = bundle.to_agent_skill()
    assert skill.id == "my-skill"
    assert skill.name == "My Skill"
    assert skill.tags == ["foo"]
    assert skill.input_modes == ["text/plain"]
    assert skill.output_modes == ["application/json"]


def test_to_agent_skill_id_fallback(tmp_path: Path) -> None:
    """When no 'id' in frontmatter, bundle.name is used as skill id."""
    _skill_md(tmp_path, "fallback", frontmatter="name: fallback\ndescription: x")
    bundle = SkillCatalog(tmp_path).bundles()[0]
    skill = bundle.to_agent_skill()
    assert skill.id == "fallback"
