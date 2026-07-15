"""Seam #13 — idempotency / resume-key provider (design seam, session.md clause 4).

Apps that need deterministic write idempotency implement this Protocol and pass
an instance to the engine at session construction time.  The kernel does not
provide a default; the reference implementation is the consuming app's record-
census mechanism.

Wire contract invariants:
- ``resume_key`` must be pure (no I/O) and return the same value for the same
  arguments across process restarts.
- ``is_idempotent_write`` receives the key produced by ``resume_key`` and returns
  ``True`` only when the write has already been committed to durable storage.
- The kernel never calls either method concurrently for the same session.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ResumableSession(Protocol):
    """App-supplied idempotency / resume-key provider (seam #13).

    Implement and register with the engine to make write operations idempotent
    across retries and resumed sessions.
    """

    def resume_key(self, job_id: str, model: str, record_index: int) -> str:
        """Return a stable, unique key for this write operation.

        The key must be deterministic: identical arguments must always produce
        the same string, including after a process restart.
        """
        ...

    def is_idempotent_write(self, key: str) -> bool:
        """Return True if the write identified by ``key`` is already committed.

        Returning True causes the engine to skip the write and treat it as a
        no-op (the prior result is still available in the session store).
        """
        ...
