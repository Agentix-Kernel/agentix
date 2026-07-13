"""Unit tests for the local file-store driver — descriptor, verbs,
containment, locking, seam construction, registry accessor, store
delegation with an injected fake backend."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentix.config import DriverSpec
from agentix.drivers import DriverInvalidRequest, DriverRegistry, FileStoreDriver
from agentix.drivers.adapters.intrinsic.local_fs import LocalFileStoreDriver
from agentix.storage.memory import MemoryLockTimeout, MemoryStore


@pytest.fixture
def driver(tmp_path: Path) -> LocalFileStoreDriver:
    return LocalFileStoreDriver(tmp_path)


# ───────────────────── descriptor + protocol ─────────────────────


def test_descriptor_is_storage_file(driver: LocalFileStoreDriver) -> None:
    assert driver.descriptor.type == "storage"
    assert driver.descriptor.modality == "file"
    assert driver.descriptor.capabilities == frozenset({"git-pin", "fcntl-lock"})


def test_protocol_structural_conformance(driver: LocalFileStoreDriver) -> None:
    assert isinstance(driver, FileStoreDriver)


# ───────────────────── verbs ─────────────────────


@pytest.mark.asyncio
async def test_write_read_append_list_exists(driver: LocalFileStoreDriver) -> None:
    await driver.write_text("pages/a.md", "alpha\n")
    await driver.append_text("pages/a.md", "more\n")
    assert await driver.read_text("pages/a.md") == "alpha\nmore\n"
    await driver.write_text("pages/deep/b.md", "beta\n")
    assert await driver.list_files("pages") == ["pages/a.md", "pages/deep/b.md"]
    assert await driver.list_files("absent") == []
    assert await driver.exists("pages/a.md") is True
    assert await driver.exists("pages/zz.md") is False


@pytest.mark.asyncio
async def test_containment_rejects_escape(driver: LocalFileStoreDriver) -> None:
    with pytest.raises(ValueError, match="escapes"):
        await driver.read_text("../outside.md")


def test_head_ref_none_outside_git(tmp_path: Path) -> None:
    assert LocalFileStoreDriver(tmp_path).head_ref() is None


@pytest.mark.asyncio
async def test_lock_contention_times_out(driver: LocalFileStoreDriver) -> None:
    async def _hold() -> None:
        async with driver.lock("res", timeout_seconds=5):
            await asyncio.sleep(0.5)

    holder = asyncio.create_task(_hold())
    await asyncio.sleep(0.05)
    with pytest.raises(MemoryLockTimeout):
        async with driver.lock("res", timeout_seconds=0.1):
            pass
    await holder


# ───────────────────── seam construction ─────────────────────


def test_spec_construction(tmp_path: Path) -> None:
    spec = DriverSpec(
        name="memory-fs",
        driver="local-file-store",
        type="storage",
        modality="file",
        options=(("root", str(tmp_path)),),
    )
    d = LocalFileStoreDriver(spec=spec, api_key=None)
    assert d.descriptor.name == "memory-fs"
    assert d.root == tmp_path.resolve()


def test_construction_without_root_or_spec_raises() -> None:
    with pytest.raises(DriverInvalidRequest):
        LocalFileStoreDriver()


# ───────────────────── registry accessor ─────────────────────


def test_registry_file_store_accessor(driver: LocalFileStoreDriver) -> None:
    reg = DriverRegistry()
    reg.register(driver)
    assert reg.file_store() is driver


# ───────────────────── store delegation ─────────────────────


class _FakeFileStore:
    """In-memory backend proving MemoryStore semantics run over any
    FileStoreDriver — the NextCloud/WebDAV shape: no git pin."""

    def __init__(self) -> None:
        from agentix.drivers import DriverDescriptor

        self.descriptor = DriverDescriptor(name="fake-fs", type="storage", modality="file", source="api")
        self.files: dict[str, str] = {}
        self.root = Path("/virtual")

    async def aclose(self) -> None: ...

    async def read_text(self, relative: str) -> str:
        if relative not in self.files:
            raise FileNotFoundError(relative)
        return self.files[relative]

    async def write_text(self, relative: str, text: str) -> None:
        self.files[relative] = text

    async def append_text(self, relative: str, text: str) -> None:
        self.files[relative] = self.files.get(relative, "") + text

    async def list_files(self, relative_dir: str, pattern: str = "*.md") -> list[str]:
        prefix = relative_dir.rstrip("/") + "/"
        return sorted(k for k in self.files if k.startswith(prefix) and k.endswith(".md"))

    async def exists(self, relative: str) -> bool:
        return relative in self.files

    def lock(self, name: str, *, timeout_seconds: float = 10.0):
        import contextlib

        @contextlib.asynccontextmanager
        async def _cm():
            yield

        return _cm()

    def head_ref(self) -> str | None:
        return None  # remote backend: version pin degrades to None


@pytest.mark.asyncio
async def test_memory_store_over_injected_driver() -> None:
    fake = _FakeFileStore()
    store = MemoryStore(driver=fake)
    await store.create_page(
        "pages/x.md",
        frontmatter_data={"title": "x"},
        sections={"Facts": "one\n"},
    )
    await store.write_section("pages/x.md", "Facts", "two")
    page = await store.read_page("pages/x.md")
    assert page.sections["Facts"].rstrip() == "two"
    await store.append_to_log(type="note", subject="s", body="b")
    assert "note | s" in fake.files["log.md"]
    assert store.head_sha() is None
    assert store.driver is fake
