"""Unit tests for MemoryStore — real markdown files under tmp_path."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentix.storage import MemoryStore
from agentix.storage.memory import MemoryPage, _split_sections

# ───────────────────────────── section parsing ─────────────────────────────


def test_split_sections_basic() -> None:
    content = "preamble\n\n## A\nalpha body\n\n## B\nbeta body\n"
    preamble, sections = _split_sections(content)
    assert preamble.strip() == "preamble"
    assert list(sections.keys()) == ["A", "B"]
    assert "alpha body" in sections["A"]
    assert "beta body" in sections["B"]


def test_split_sections_no_h2_returns_all_as_preamble() -> None:
    content = "just some body\nno headings\n"
    preamble, sections = _split_sections(content)
    assert preamble == content
    assert sections == {}


def test_split_sections_empty_preamble_when_h2_first() -> None:
    content = "## Only\nbody\n"
    preamble, sections = _split_sections(content)
    assert preamble == ""
    assert sections == {"Only": "body\n"}


# ───────────────────────────── round-trip ──────────────────────────────────


@pytest.mark.asyncio
async def test_create_and_read_page(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    await memory.create_page(
        "customers/example.md",
        frontmatter_data={"customer_id": "example", "last_session": "2026-04-20"},
        sections={
            "Work context": "Customer runs Odoo V9.\n",
            "Top-of-mind": "nothing active.\n",
        },
    )
    page = await memory.read_page("customers/example.md")
    assert page.frontmatter["customer_id"] == "example"
    assert list(page.sections.keys()) == ["Work context", "Top-of-mind"]
    assert "Customer runs Odoo V9" in page.sections["Work context"]


@pytest.mark.asyncio
async def test_write_section_preserves_other_sections(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    await memory.create_page(
        "customers/example.md",
        frontmatter_data={"customer_id": "example"},
        sections={
            "Work context": "original work context\n",
            "Historical context": "do not touch me\n",
            "Top-of-mind": "stale\n",
        },
    )
    await memory.write_section("customers/example.md", "Top-of-mind", "fresh active session\n")
    page = await memory.read_page("customers/example.md")
    assert "original work context" in page.sections["Work context"]
    assert "do not touch me" in page.sections["Historical context"]
    assert "fresh active session" in page.sections["Top-of-mind"]


@pytest.mark.asyncio
async def test_write_section_appends_when_missing(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    await memory.create_page(
        "customers/example.md",
        frontmatter_data={"customer_id": "example"},
        sections={"Work context": "baseline\n"},
    )
    await memory.write_section("customers/example.md", "Facts", "new fact\n")
    page = await memory.read_page("customers/example.md")
    assert "Facts" in page.sections
    assert "Work context" in page.sections


@pytest.mark.asyncio
async def test_update_frontmatter_preserves_body(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    await memory.create_page(
        "renames/v9-to-v18.md",
        frontmatter_data={"evidence_count": 1, "confirmed_by": ["a"]},
        sections={"body": "text\n"},
    )
    await memory.update_frontmatter("renames/v9-to-v18.md", {"evidence_count": 2, "confirmed_by": ["a", "b"]})
    page = await memory.read_page("renames/v9-to-v18.md")
    assert page.frontmatter["evidence_count"] == 2
    assert page.frontmatter["confirmed_by"] == ["a", "b"]
    assert "text" in page.sections["body"]


# ───────────────────────────────── log ─────────────────────────────────────


@pytest.mark.asyncio
async def test_append_to_log_writes_grep_friendly_header(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    await memory.append_to_log(kind="ingest", subject="example session 1")
    text = memory.path_log().read_text(encoding="utf-8")
    assert text.startswith("## [")
    assert "ingest | example session 1" in text


@pytest.mark.asyncio
async def test_concurrent_log_appends_preserve_line_integrity(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    await asyncio.gather(*(memory.append_to_log(kind="ingest", subject=f"subject-{i}") for i in range(30)))
    text = memory.path_log().read_text(encoding="utf-8")
    for i in range(30):
        assert f"subject-{i}" in text
    # headers must not interleave with each other; every "## [" should begin a
    # line
    heading_count = sum(1 for line in text.splitlines() if line.startswith("## ["))
    assert heading_count == 30


# ──────────────────────────────── safety ───────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_rejects_path_traversal(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        await memory.read_page("../outside.md")


# ─────────────────────────── per-customer lock (PR-I) ──────────────────


@pytest.mark.asyncio
async def test_lock_for_customer_serialises_concurrent_sections(tmp_path: Path) -> None:
    """Two racers writing the same customer page observe last-writer-wins
    without losing data under the lock — each block they write survives."""
    from agentix.storage import MemoryStore

    memory = MemoryStore(tmp_path)
    await memory.create_page(
        "customers/example.md",
        frontmatter_data={},
        sections={"Facts": "seed\n"},
    )
    completed: list[str] = []

    async def racer(tag: str) -> None:
        async with memory.lock_for_customer("example", timeout_seconds=5.0):
            existing = (await memory.read_page("customers/example.md")).sections["Facts"]
            await asyncio.sleep(0.01)  # widen the race window
            await memory.write_section(
                "customers/example.md",
                "Facts",
                existing + f"{tag}\n",
            )
            completed.append(tag)

    await asyncio.gather(racer("a"), racer("b"), racer("c"))
    assert sorted(completed) == ["a", "b", "c"]
    final = (await memory.read_page("customers/example.md")).sections["Facts"]
    # Every racer's tag survives — the earlier `existing` read happened
    # under the lock so each subsequent writer saw the previous one's bytes.
    for tag in ("a", "b", "c"):
        assert tag in final, final


@pytest.mark.asyncio
async def test_lock_for_customer_times_out_when_held(tmp_path: Path) -> None:
    """A second acquire with a tight timeout raises MemoryLockTimeout
    while the first holder is still inside its context."""
    from agentix.storage import MemoryLockTimeout, MemoryStore

    memory = MemoryStore(tmp_path)

    holder_acquired = asyncio.Event()
    holder_release = asyncio.Event()

    async def holder() -> None:
        async with memory.lock_for_customer("example", timeout_seconds=5.0):
            holder_acquired.set()
            await holder_release.wait()

    task = asyncio.create_task(holder())
    try:
        await holder_acquired.wait()
        # Timeout-bounded attempt while the holder is still in the lock
        # → we expect MemoryLockTimeout.
        with pytest.raises(MemoryLockTimeout):
            async with memory.lock_for_customer("example", timeout_seconds=0.05):
                raise AssertionError("should not have acquired the lock")
    finally:
        holder_release.set()
        await task


@pytest.mark.asyncio
async def test_lock_for_customer_creates_lock_dir(tmp_path: Path) -> None:
    from agentix.storage import MemoryStore

    memory = MemoryStore(tmp_path / "fresh")
    memory.root.mkdir(parents=True)
    async with memory.lock_for_customer("example"):
        pass
    # Path now namespaced as "customer-<id>.lock" — wrapper added when
    # the generic ``MemoryStore.lock(name)`` method was introduced so
    # customer locks can coexist with reconcile-key locks without
    # collision.
    assert (memory.root / ".locks" / "customer-example.lock").exists()


# ───────────────────────────── list_pages ──────────────────────────────────


@pytest.mark.asyncio
async def test_list_pages_returns_sorted_md(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    for name in ["zz", "aa", "mm"]:
        await memory.create_page(
            f"renames/{name}.md",
            frontmatter_data={},
            sections={"body": ""},
        )
    pages = await memory.list_pages("renames")
    names = [p.name for p in pages]
    assert names == ["aa.md", "mm.md", "zz.md"]


# ──────────────────────────── orphan detection ─────────────────────────────


@pytest.mark.asyncio
async def test_find_orphan_pages_skips_referenced_pages(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    # index.md references renames/a.md but not renames/orphan.md
    (tmp_path / "index.md").write_text("see [a](renames/a.md)\n", encoding="utf-8")
    await memory.create_page("renames/a.md", frontmatter_data={}, sections={"b": ""})
    await memory.create_page("renames/orphan.md", frontmatter_data={}, sections={"b": ""})
    orphans = await memory.find_orphan_pages("renames")
    assert {p.name for p in orphans} == {"orphan.md"}


# ──────────────────────────────── promote ──────────────────────────────────


@pytest.mark.asyncio
async def test_promote_evidence_grows_confirmed_by(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    await memory.create_page(
        "renames/v9-to-v18.md",
        frontmatter_data={"evidence_count": 1, "confirmed_by": ["cust_a"]},
        sections={"Notes": "initial\n"},
    )
    promoted = await memory.promote_evidence(
        target_relative="renames/v9-to-v18.md",
        customer_id="cust_b",
        threshold=3,
    )
    assert promoted is False
    page = await memory.read_page("renames/v9-to-v18.md")
    assert page.frontmatter["confirmed_by"] == ["cust_a", "cust_b"]
    assert page.frontmatter["evidence_count"] == 2

    # cross the threshold
    promoted = await memory.promote_evidence(
        target_relative="renames/v9-to-v18.md",
        customer_id="cust_c",
        threshold=3,
    )
    assert promoted is True


@pytest.mark.asyncio
async def test_promote_evidence_is_idempotent(tmp_path: Path) -> None:
    memory = MemoryStore(tmp_path)
    await memory.create_page(
        "renames/v9-to-v18.md",
        frontmatter_data={"evidence_count": 1, "confirmed_by": ["cust_a"]},
        sections={"Notes": "initial\n"},
    )
    for _ in range(3):
        await memory.promote_evidence(
            target_relative="renames/v9-to-v18.md",
            customer_id="cust_a",
            threshold=3,
        )
    page = await memory.read_page("renames/v9-to-v18.md")
    assert page.frontmatter["confirmed_by"] == ["cust_a"]
    assert page.frontmatter["evidence_count"] == 1


# ──────────────────────── page dataclass round-trip ────────────────────────


def test_memory_page_render_round_trip() -> None:
    page = MemoryPage(
        frontmatter={"customer_id": "example"},
        preamble="> top note\n",
        sections={"Work context": "x\n", "Top-of-mind": "y\n"},
    )
    text = page.render()
    assert "---" in text
    assert "## Work context" in text
    assert "## Top-of-mind" in text
    assert "customer_id: example" in text
