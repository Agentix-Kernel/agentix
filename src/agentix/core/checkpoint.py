"""Named checkpoints for operator-facing resume.

Checkpoint granularity is hybrid. Every turn writes the ``"latest"``
snapshot via ``session.save``. Named checkpoints land at whatever
boundaries the app cares about and are the ones operators reach for on
resume.

The name is an arbitrary string — the kernel names no phase vocabulary.
Apps that want an ordered set of phase checkpoints declare and validate
that vocabulary themselves.
"""

from __future__ import annotations

from agentix.core.session import Session, save
from agentix.storage import MinioStore, SqliteStore

# An app-defined checkpoint label. Generic on purpose — the kernel imposes no
# phase order; the app supplies its own vocabulary.
CheckpointName = str


async def save_checkpoint(
    session: Session,
    name: CheckpointName,
    *,
    sqlite: SqliteStore,
    minio: MinioStore,
) -> str:
    """Save a named checkpoint. Delegates to ``session.save``.

    Returns the MinIO key for the written blob.
    """
    return await save(session, sqlite=sqlite, minio=minio, checkpoint=name)


async def load_checkpoint(
    customer_id: str,
    session_id: str,
    name: CheckpointName,
    *,
    minio: MinioStore,
) -> dict[str, object]:
    """Return the raw JSON snapshot for a named checkpoint."""
    key = MinioStore.key_checkpoint(customer_id, session_id, name)
    result = await minio.get_json(key)
    if not isinstance(result, dict):
        raise ValueError(f"checkpoint {key} is not a JSON object")
    return result
