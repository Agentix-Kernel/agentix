"""SSE framing codec for the Contract A event stream (`id:`/`event:`/`data:`).

One canonical implementation of the wire format that the gateway *encodes* and thin clients
*decode* (CRIE R-3 — previously hand-rolled in ludo-gateway projector + ludo-cli client).

`decode_sse` is client-safe (used by public clients). `encode_sse` is used by the gateway
relay. Contract A is SSE, NOT NDJSON — see contracts/README.md.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any


def encode_sse(seq: int, event_type: str, payload: Any) -> str:
    """Render one resumable SSE frame. `seq` is the JetStream sequence (the Last-Event-ID)."""
    data = json.dumps(payload, separators=(",", ":"))
    return f"id: {seq}\nevent: {event_type}\ndata: {data}\n\n"


def decode_sse(lines: Iterable[str]) -> Iterator[tuple[int, str, Any]]:
    """Parse an SSE line stream into `(seq, type, payload)` tuples.

    Accumulates multi-line `data:` fields; emits on the blank-line frame boundary. `payload`
    is JSON-decoded when possible, else the raw string. `seq` carries forward when a frame
    has no `id:` (SSE semantics), so a reconnect can resume from the last seen sequence.
    """
    seq = 0
    etype = "message"
    data_buf: list[str] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if line == "":  # frame boundary
            if data_buf:
                body = "\n".join(data_buf)
                try:
                    payload: Any = json.loads(body)
                except json.JSONDecodeError:
                    payload = body
                yield (seq, etype, payload)
            etype, data_buf = "message", []
            continue
        if line.startswith("id:"):
            val = line[3:].strip()
            seq = int(val) if val.isdigit() else seq
        elif line.startswith("event:"):
            etype = line[6:].strip()
        elif line.startswith("data:"):
            data_buf.append(line[5:].lstrip())
