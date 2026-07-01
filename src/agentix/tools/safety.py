"""SafetyGate — the kernel verify-then-rollback contract per tool call.

For a tool with ``mutates_target=True``: block on dry-run; require a declared verifier;
run the tool; run the verifier; on drift, roll back and raise ``SafetyVerifyFailed``.
Non-mutating tools pass straight through.

The kernel ships the generic flow + exceptions. The two app-specific seams are abstract
hooks an app overrides:

* :meth:`SafetyGate.rollback` — how to undo a mutation that failed verification (e.g. the
  migration app's xmlid-prefixed unlink). The base raises ``NotImplementedError``.
* :meth:`SafetyGate._resolve_contract` — optional per-model verify contract + derived
  check fields. The base returns ``(None, [])`` (count + sample verification only).
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from pydantic import BaseModel

from agentix.storage import SqliteStore
from agentix.tools.base import Tool, ToolContext

log = structlog.get_logger(__name__)


class SafetyError(Exception):
    """Base for safety-layer exceptions; catch all via ``except SafetyError``."""


class SafetyGateBlocked(SafetyError):
    """Raised when a mutating tool call is blocked by dry-run mode."""


class SafetyInvariantViolated(SafetyError):
    """Raised when a mutating tool doesn't declare a verifier."""


class SafetyVerifyFailed(SafetyError):
    """Raised when the verifier reports drift after a mutating call; rollback has already run."""

    def __init__(self, message: str, findings: list[Any]) -> None:
        super().__init__(message)
        self.findings = findings


class SafetyGate:
    """Executes tools with the verify-then-rollback guarantees.

    App-agnostic. Override :meth:`rollback` (required for any app with mutating tools) and
    optionally :meth:`_resolve_contract`.
    """

    def __init__(self, *, sqlite: SqliteStore) -> None:
        self._sqlite = sqlite

    async def execute(
        self,
        tool: Tool,
        input: BaseModel,
        ctx: ToolContext,
    ) -> BaseModel:
        # Non-mutating tools run unconditionally.
        if not tool.mutates_target:
            return await tool.call(input, ctx)

        # Dry-run intercept.
        if ctx.dry_run:
            detail = _serialise(input)
            await self._sqlite.append_safety_event(
                session_id=ctx.session.id,
                kind="dry_run_block",
                tool_name=tool.name,
                tool_input=detail,
            )
            log.info(
                "safety.dry_run_block",
                session_id=ctx.session.id,
                tool=tool.name,
            )
            raise SafetyGateBlocked(f"{tool.name}: blocked by dry-run mode")

        # Invariant: mutating tools MUST declare a verifier.
        if not tool.verifier:
            raise SafetyInvariantViolated(f"{tool.name}: mutates_target=True but no verifier declared")

        # Run the tool; app-side atomicity is per-RPC.
        result = await tool.call(input, ctx)

        # Empty ``verify_scope`` on the output means the tool mutated
        # nothing — skip verification.
        verify_scope = getattr(result, "verify_scope", None)
        if isinstance(verify_scope, list) and not verify_scope:
            log.info(
                "safety.verify_skipped_empty_scope",
                session_id=ctx.session.id,
                tool=tool.name,
            )
            return result

        # Verify.
        verifier = _resolve_verifier(ctx, tool.verifier)
        verify_input = _build_verifier_input(
            verifier,
            input,
            result,
            contract_resolver=lambda model: self._resolve_contract(ctx, model),
        )
        verify_result = await verifier.call(verify_input, ctx)
        ok = bool(getattr(verify_result, "ok", True))

        if ok:
            log.info(
                "safety.verify_ok",
                session_id=ctx.session.id,
                tool=tool.name,
                verifier=verifier.name,
            )
            return result

        # Drift detected — per-batch verify failure, then app rollback, then raise.
        findings = list(getattr(verify_result, "findings", []) or [])
        model_hint = getattr(verify_result, "model", None)
        await self._sqlite.append_safety_event(
            session_id=ctx.session.id,
            kind="per_batch_verify_fail",
            tool_name=tool.name,
            tool_input=_serialise(input),
            detail=json.dumps([_finding_repr(f) for f in findings], default=str)[:2000],
        )

        await self.rollback(
            ctx,
            tool=tool,
            input=input,
            model=str(model_hint) if model_hint else None,
        )
        raise SafetyVerifyFailed(
            f"{tool.name}: verifier {verifier.name} reported drift — rolled back",
            findings=findings,
        )

    async def rollback(
        self,
        ctx: ToolContext,
        *,
        tool: Tool,
        input: BaseModel,
        model: str | None,
    ) -> None:
        """Undo a mutation that failed verification. App-specific — must be overridden.

        Implementations should log a ``safety_events`` row describing the rollback.
        """
        raise NotImplementedError("SafetyGate.rollback must be implemented by the app")

    def _resolve_contract(self, ctx: ToolContext, model: str | None) -> tuple[Any, list[str]]:
        """Return ``(verify_contract, derived_check_fields)`` for ``model``.

        The kernel default is ``(None, [])`` (no contract — count + sample verification
        only). Apps with a per-model contract substrate override this.
        """
        return None, []


_MISSING: Any = object()


def _resolve_verifier(ctx: ToolContext, verifier_name: str) -> Tool:
    if ctx.registry is None:
        raise SafetyInvariantViolated(f"SafetyGate needs ctx.registry to resolve verifier {verifier_name!r}")
    return ctx.registry.get(verifier_name)


def _build_verifier_input(
    verifier: Tool,
    source_input: BaseModel,
    tool_output: BaseModel | None = None,
    *,
    contract_resolver: Any = None,
) -> BaseModel:
    """Construct the verifier's input model from the source-tool input.

    Forwards fields shared by name with the verifier's input schema. A non-empty
    ``verify_scope`` on ``tool_output`` is forwarded as ``batch_scope`` to scope the verify
    to exactly those records.

    :param contract_resolver: callable taking the model name and returning
        ``(verify_contract, derived_check_fields)``; the contract drives field-level checks.
        ``(None, [])`` means count + sample only.
    """
    source = source_input.model_dump()
    target_schema = verifier.input_schema
    target_fields = target_schema.model_fields.keys()
    payload = {k: v for k, v in source.items() if k in target_fields}
    # Forward rename_map.target_model so the verifier filters on the target
    # model name, not the source name.
    if "target_model" in target_fields and not payload.get("target_model"):
        rmap = source.get("rename_map")
        if isinstance(rmap, dict) and rmap.get("target_model"):
            payload["target_model"] = str(rmap["target_model"])
    runtime_scope = getattr(tool_output, "verify_scope", None)
    if runtime_scope and "batch_scope" in target_fields:
        payload["batch_scope"] = list(runtime_scope)
    if contract_resolver is not None:
        model_name = payload.get("model") or source.get("model")
        contract, derived = contract_resolver(model_name)
        if contract is not None and "contract" in target_fields:
            payload["contract"] = contract
        # Populate check_fields only when the source tool didn't declare it.
        if derived and "check_fields" in target_fields and not payload.get("check_fields"):
            payload["check_fields"] = derived
    return target_schema.model_validate(payload)


def _serialise(model: BaseModel) -> str:
    try:
        return json.dumps(model.model_dump(), default=str)[:2000]
    except Exception:
        return repr(model)[:2000]


def _finding_repr(finding: Any) -> Any:
    """Best-effort serialisation of a verifier finding (BaseModel or plain)."""
    if isinstance(finding, BaseModel):
        return finding.model_dump()
    return finding
