"""File-store driver family — the storage-type file transport.

Phase 3 of the storage driver split: ``MemoryStore`` stays the semantic
layer — frontmatter, section-preserving writes, orphan lint, evidence
promotion — while the physical medium (read/write/append/list/lock)
lives behind this protocol. The local filesystem is the landed backend;
a NextCloud/WebDAV or SMB backend is a new adapter, app-side via the
driver seam.

Paths are **relative POSIX strings** rooted at the backend's root —
backend-neutral; only the local adapter can hand out absolute ``Path``s.

Two honest boundaries, designed in rather than hidden:

* **Locking is a verb.** Advisory locking is backend-specific (fcntl
  locally, WebDAV LOCK remotely) — so ``lock()`` is part of the protocol,
  not an add-on. Timeout raises a ``TimeoutError`` subclass (the local
  adapter raises ``storage.memory.MemoryLockTimeout`` so existing
  handlers keep working).
* **The version pin degrades.** ``head_ref()`` returns the git HEAD sha
  locally and ``None`` on backends without a repo — callers already
  treat None as "no pin, no drift check".
"""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import Protocol, runtime_checkable

from agentix.drivers.base import Driver

__all__ = ["FileStoreDriver"]


@runtime_checkable
class FileStoreDriver(Driver, Protocol):
    """Protocol every file-store adapter implements — storage-type,
    ``modality="file"``.

    Error contract: local I/O errors (``FileNotFoundError``, ``OSError``)
    propagate as-is — they are meaningful to callers; remote adapters
    classify connectivity into ``DriverUnavailable``. Lock acquisition
    timeout raises a ``TimeoutError`` subclass.
    """

    async def read_text(self, relative: str) -> str: ...

    async def write_text(self, relative: str, text: str) -> None:
        """Write (create or overwrite), creating parent directories."""
        ...

    async def append_text(self, relative: str, text: str) -> None:
        """Append to the file, creating it (and parents) when absent."""
        ...

    async def list_files(self, relative_dir: str, pattern: str = "*.md") -> list[str]:
        """Relative POSIX paths of matching files under ``relative_dir``,
        recursive, sorted. Empty list when the directory does not exist."""
        ...

    async def exists(self, relative: str) -> bool: ...

    def lock(self, name: str, *, timeout_seconds: float = 10.0) -> AbstractAsyncContextManager[None]:
        """Advisory lock keyed by ``name`` — serialises read-merge-write
        workflows across tasks and processes (backend-specific mechanism)."""
        ...

    def head_ref(self) -> str | None:
        """Version pin of the store's current state (git HEAD sha locally);
        None when the backend cannot provide one."""
        ...
