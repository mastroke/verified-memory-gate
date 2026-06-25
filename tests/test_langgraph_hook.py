"""Tests for LangGraph integration hook (roadmap r6)."""

from __future__ import annotations

from verified_memory_gate import (
    CommitStatus,
    DistillContext,
    EDVPipeline,
    ExecuteStage,
    ExecutorTrace,
    GateMode,
    InMemoryStore,
    MemoryGate,
    MemoryScope,
)
from verified_memory_gate.langgraph_hook import (
    DEFAULT_BLOCKED_MEMORY_TOOLS,
    STATE_BLOCKED_TOOLS,
    STATE_DISTILL_CONTEXT,
    STATE_MEMORY_REJECTIONS,
    STATE_MEMORY_RESULT,
    STATE_MEMORY_REVIEW,
    STATE_TRACES,
    MemoryToolGuard,
    guard_tool_call,
    make_propose_memory_node,
    propose_memory,
    serialize_commit_result,
)
from tests.conftest import distill_context, dual_traces, gate  # noqa: F401


def test_propose_memory_commits_valid_traces(gate: MemoryGate) -> None:
    lesson = "Gate walk-forward splits with embargo before promotion."
    state = {
        STATE_TRACES: dual_traces(lesson, trace_id="wf-9"),
        STATE_DISTILL_CONTEXT: distill_context(
            principal="research-agent",
            scope=MemoryScope.TEAM,
            trace_id="wf-9",
        ),
    }

    patch = propose_memory(state, gate)

    assert patch[STATE_MEMORY_RESULT]["status"] == CommitStatus.COMMITTED.value
    assert patch[STATE_MEMORY_RESULT]["committed"] is True
    assert patch[STATE_MEMORY_REJECTIONS] == ()
    assert patch[STATE_MEMORY_REVIEW] is False
    assert patch["memory_id"] is not None
    assert gate.store.count() == 1


def test_propose_memory_surfaces_rejection_reasons(gate: MemoryGate) -> None:
    state = {
        STATE_TRACES: dual_traces("Some lesson"),
        STATE_DISTILL_CONTEXT: DistillContext(principal="", scope=MemoryScope.PRIVATE),
    }

    patch = propose_memory(state, gate)

    assert patch[STATE_MEMORY_RESULT]["status"] == CommitStatus.REJECTED.value
    assert patch[STATE_MEMORY_RESULT]["rejected"] is True
    assert any("principal is required" in r for r in patch[STATE_MEMORY_REJECTIONS])
    assert patch[STATE_MEMORY_REVIEW] is True
    assert gate.store.count() == 0


def test_propose_memory_pending_sets_review_flag(gate: MemoryGate) -> None:
    gate.mode = GateMode.MANUAL_REVIEW
    state = {
        STATE_TRACES: dual_traces("Awaiting human approval."),
        STATE_DISTILL_CONTEXT: distill_context(principal="agent-a", scope="private"),
    }

    patch = propose_memory(state, gate)

    assert patch[STATE_MEMORY_RESULT]["status"] == CommitStatus.PENDING.value
    assert patch[STATE_MEMORY_RESULT]["pending"] is True
    assert patch[STATE_MEMORY_REVIEW] is True
    assert patch["pending_id"] is not None
    assert len(gate.list_pending()) == 1


def test_propose_memory_accepts_dict_traces_and_context(gate: MemoryGate) -> None:
    state = {
        STATE_TRACES: (
            {
                "executor_id": "research-agent",
                "content": "Dict-encoded trace lesson.",
                "trace_id": "dict-1",
                "evidence": ["pytest:passed"],
            },
            {
                "executor_id": "audit-agent",
                "content": "cross-check: Dict-encoded trace lesson.",
                "trace_id": "dict-1",
            },
        ),
        STATE_DISTILL_CONTEXT: {
            "principal": "research-agent",
            "scope": "team",
            "relationship": "derived_from",
            "classification": "episodic",
            "trace_id": "dict-1",
        },
    }

    patch = propose_memory(state, gate)

    assert patch[STATE_MEMORY_RESULT]["committed"] is True


def test_propose_memory_rejects_missing_traces(gate: MemoryGate) -> None:
    patch = propose_memory({STATE_DISTILL_CONTEXT: distill_context()}, gate)

    assert patch[STATE_MEMORY_RESULT]["rejected"] is True
    assert "no executor traces" in patch[STATE_MEMORY_REJECTIONS][0]


def test_make_propose_memory_node_runs_as_langgraph_node(gate: MemoryGate) -> None:
    node = make_propose_memory_node(gate)
    state = {
        STATE_TRACES: dual_traces("Node wrapper lesson."),
        STATE_DISTILL_CONTEXT: distill_context(principal="agent-a", scope="private"),
    }

    patch = node(state)

    assert patch[STATE_MEMORY_RESULT]["committed"] is True


def test_guard_blocks_direct_memory_tools() -> None:
    guard = MemoryToolGuard()
    for tool_name in DEFAULT_BLOCKED_MEMORY_TOOLS:
        assert guard.is_blocked(tool_name)
        blocked = guard.intercept(tool_name, {"lesson": "bypass attempt"})
        assert blocked is not None
        assert "blocked" in blocked.reason


def test_guard_allows_non_memory_tools() -> None:
    guard = MemoryToolGuard()
    assert guard.intercept("search_docs", {"query": "sharpe"}) is None


def test_guard_tool_call_patches_state_for_human_review() -> None:
    state: dict[str, object] = {}

    patch, error = guard_tool_call(state, "save_memory", {"lesson": "direct write"})

    assert error is not None
    assert patch is not None
    assert patch[STATE_MEMORY_REVIEW] is True
    assert patch[STATE_MEMORY_REJECTIONS] == (error,)
    blocked = patch[STATE_BLOCKED_TOOLS]
    assert len(blocked) == 1
    assert blocked[0]["tool_name"] == "save_memory"


def test_guard_tool_call_accumulates_blocked_attempts() -> None:
    state = {
        STATE_BLOCKED_TOOLS: (
            {"tool_name": "write_memory", "reason": "first", "arguments": {}},
        ),
    }

    patch, _ = guard_tool_call(state, "store_memory", {"content": "x"})

    assert patch is not None
    assert len(patch[STATE_BLOCKED_TOOLS]) == 2


def test_guard_tool_call_passes_through_allowed_tools() -> None:
    patch, error = guard_tool_call({}, "run_backtest", {"strategy": "mom-v2"})

    assert patch is None
    assert error is None


def test_serialize_commit_result_round_trips_status_fields() -> None:
    gate = MemoryGate(
        store=InMemoryStore(),
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
    )
    traces = (
        ExecutorTrace(executor_id="a", content="lesson"),
    )
    context = DistillContext(
        principal="agent",
        scope=MemoryScope.PRIVATE,
    )
    result = gate.commit(traces, context)
    payload = serialize_commit_result(result)

    assert payload["status"] == result.status.value
    assert payload["committed"] == result.committed
    assert payload["reasons"] == list(result.reasons)
