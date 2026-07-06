"""Engine core — session, checkpoint, context, and the engine/turn dispatcher.

The kernel spine: the ``Turn``/``Message`` types, the ``Session`` lifecycle + resumable
checkpoints, the context builder, and the ``Engine`` that drives the middleware chain.
App-specific core modules (rename maps, reconnaissance, diagnosis, the Odoo-aware
dispatcher) live in the app's own ``*.core`` package and depend on this surface.
"""

from agentix.core.checkpoint import (
    ORDERED_CHECKPOINTS,
    CheckpointName,
    load_checkpoint,
    save_checkpoint,
)
from agentix.core.context import (
    CompressionStrategy,
    ContextBudget,
    ContextBuilder,
    summarise_oldest_tool_results,
)
from agentix.core.engine import Engine, TurnDispatcher
from agentix.core.session import Session, create_session, resume_from, resume_or_create, save
from agentix.core.types import (
    Message,
    TokenUsage,
    ToolCall,
    ToolCallResult,
    Turn,
    TurnStatus,
)

__all__ = [
    "ORDERED_CHECKPOINTS",
    "CheckpointName",
    "CompressionStrategy",
    "ContextBudget",
    "ContextBuilder",
    "Engine",
    "Message",
    "Session",
    "TokenUsage",
    "ToolCall",
    "ToolCallResult",
    "Turn",
    "TurnDispatcher",
    "TurnStatus",
    "create_session",
    "load_checkpoint",
    "resume_from",
    "resume_or_create",
    "save",
    "save_checkpoint",
    "summarise_oldest_tool_results",
]
