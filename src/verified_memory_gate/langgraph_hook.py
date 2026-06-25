"""LangGraph-compatible middleware for gated memory proposals."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from verified_memory_gate.edv import DistillContext, ExecutorTrace
from verified_memory_gate.gate import MemoryGate
from verified_memory_gate.models import CommitResult, CommitStatus, MemoryScope

# Agent-state keys expected by orchestrators wiring this hook.
STATE_TRACES = "executor_traces"
STATE_DISTILL_CONTEXT = "distill_context"
STATE_MEMORY_RESULT = "memory_commit_result"
STATE_MEMORY_REJECTIONS = "memory_rejection_reasons"
STATE_BLOCKED_TOOLS = "blocked_memory_tool_calls"
STATE_MEMORY_REVIEW = "memory_review_required"

DEFAULT_BLOCKED_MEMORY_TOOLS = frozenset(
    {
        "save_memory",
        "write_memory",
        "store_memory",
        "add_memory",
        "insert_memory",
        "update_memory",
        "persist_memory",
    }
)

StatePatch = dict[str, Any]
StateReader = Mapping[str, Any]
MiddlewareNode = Callable[[StateReader], StatePatch]


@dataclass(frozen=True, slots=True)
class BlockedToolCall:
    """Record of a direct memory tool call rejected by the gate hook."""

    tool_name: str
    reason: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MemoryToolGuard:
    """Reject tool calls that bypass ``MemoryGate.commit``."""

    blocked_tools: frozenset[str] = DEFAULT_BLOCKED_MEMORY_TOOLS
    bypass_message: str = (
        "direct memory tools are blocked; lessons must flow through "
        "post-run propose_memory middleware and MemoryGate.commit"
    )

    def is_blocked(self, tool_name: str) -> bool:
        return tool_name.strip().lower() in self.blocked_tools

    def intercept(
        self,
        tool_name: str,
        arguments: Mapping[str, Any] | None = None,
    ) -> BlockedToolCall | None:
        if not self.is_blocked(tool_name):
            return None
        return BlockedToolCall(
            tool_name=tool_name,
            reason=self.bypass_message,
            arguments=dict(arguments or {}),
        )


def serialize_commit_result(result: CommitResult) -> dict[str, Any]:
    """Convert a commit outcome into a JSON-friendly agent-state fragment."""
    return {
        "status": result.status.value,
        "memory_id": result.memory_id,
        "pending_id": result.pending_id,
        "reasons": list(result.reasons),
        "committed": result.committed,
        "rejected": result.rejected,
        "pending": result.pending,
    }


def _coerce_trace(raw: ExecutorTrace | Mapping[str, Any]) -> ExecutorTrace:
    if isinstance(raw, ExecutorTrace):
        return raw
    evidence = raw.get("evidence", ())
    if isinstance(evidence, list):
        evidence = tuple(evidence)
    metadata = raw.get("metadata", {})
    return ExecutorTrace(
        executor_id=str(raw["executor_id"]),
        content=str(raw["content"]),
        trace_id=raw.get("trace_id"),
        evidence=tuple(evidence),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _coerce_traces(
    raw: Sequence[ExecutorTrace | Mapping[str, Any]],
) -> tuple[ExecutorTrace, ...]:
    return tuple(_coerce_trace(item) for item in raw)


def _coerce_context(raw: DistillContext | Mapping[str, Any]) -> DistillContext:
    if isinstance(raw, DistillContext):
        return raw
    scope = raw.get("scope", MemoryScope.PRIVATE)
    metadata = raw.get("metadata", {})
    return DistillContext(
        principal=str(raw["principal"]),
        scope=scope,
        relationship=str(raw.get("relationship", "derived_from")),
        classification=str(raw.get("classification", "episodic")),
        trace_id=raw.get("trace_id"),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _rejection_patch(
    result: CommitResult,
    *,
    review_required: bool | None = None,
) -> StatePatch:
    needs_review = (
        result.pending or result.rejected
        if review_required is None
        else review_required
    )
    patch: StatePatch = {
        STATE_MEMORY_RESULT: serialize_commit_result(result),
        STATE_MEMORY_REJECTIONS: result.reasons,
        STATE_MEMORY_REVIEW: needs_review,
    }
    if result.memory_id is not None:
        patch["memory_id"] = result.memory_id
    if result.pending_id is not None:
        patch["pending_id"] = result.pending_id
    return patch


def propose_memory(
    state: StateReader,
    gate: MemoryGate,
    *,
    traces_key: str = STATE_TRACES,
    context_key: str = STATE_DISTILL_CONTEXT,
) -> StatePatch:
    """Post-run middleware: commit traces through EDV and surface outcomes."""
    traces_raw = state.get(traces_key)
    if not traces_raw:
        return _rejection_patch(
            CommitResult(
                status=CommitStatus.REJECTED,
                reasons=("no executor traces in agent state",),
            )
        )

    context_raw = state.get(context_key)
    if context_raw is None:
        return _rejection_patch(
            CommitResult(
                status=CommitStatus.REJECTED,
                reasons=("distill context missing from agent state",),
            )
        )

    traces = _coerce_traces(traces_raw)
    context = _coerce_context(context_raw)
    result = gate.commit(traces, context)
    return _rejection_patch(result)


def make_propose_memory_node(
    gate: MemoryGate,
    *,
    traces_key: str = STATE_TRACES,
    context_key: str = STATE_DISTILL_CONTEXT,
) -> MiddlewareNode:
    """Return a LangGraph node that proposes experiences after agent execution."""

    def node(state: StateReader) -> StatePatch:
        return propose_memory(
            state,
            gate,
            traces_key=traces_key,
            context_key=context_key,
        )

    return node


def _append_blocked_call(
    state: StateReader,
    blocked: BlockedToolCall,
    *,
    blocked_key: str = STATE_BLOCKED_TOOLS,
) -> tuple[Any, ...]:
    existing = state.get(blocked_key, ())
    entry = {
        "tool_name": blocked.tool_name,
        "reason": blocked.reason,
        "arguments": blocked.arguments,
    }
    if isinstance(existing, list):
        return (*tuple(existing), entry)
    if isinstance(existing, tuple):
        return (*existing, entry)
    return (entry,)


def merge_blocked_tool(
    state: StateReader,
    blocked: BlockedToolCall,
    *,
    blocked_key: str = STATE_BLOCKED_TOOLS,
) -> StatePatch:
    """Record a blocked tool call and surface its reason for human review."""
    return {
        blocked_key: _append_blocked_call(state, blocked, blocked_key=blocked_key),
        STATE_MEMORY_REJECTIONS: (blocked.reason,),
        STATE_MEMORY_REVIEW: True,
    }


def guard_tool_call(
    state: StateReader,
    tool_name: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    guard: MemoryToolGuard | None = None,
) -> tuple[StatePatch | None, str | None]:
    """Block direct memory tools; return a state patch when intercepted."""
    active_guard = guard or MemoryToolGuard()
    blocked = active_guard.intercept(tool_name, arguments)
    if blocked is None:
        return None, None
    return merge_blocked_tool(state, blocked), blocked.reason
