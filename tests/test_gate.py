"""Tests for the memory write interceptor API (roadmap r1)."""

from __future__ import annotations

import pytest

from verified_memory_gate import (
    CommitStatus,
    DistillContext,
    EDVPipeline,
    ExecuteStage,
    GateMode,
    InMemoryStore,
    MemoryGate,
    MemoryScope,
    RetrievalFilter,
)
from tests.conftest import distill_context, dual_traces, gate  # noqa: F401


def test_commit_valid_experience(gate: MemoryGate) -> None:
    lesson = "Use walk-forward split with embargo for backtests."
    traces = dual_traces(lesson, trace_id="run-42", evidence=("pytest:passed",))
    context = distill_context(
        principal="research-agent",
        scope=MemoryScope.TEAM,
        trace_id="run-42",
    )

    result = gate.commit(traces, context)

    assert result.status is CommitStatus.COMMITTED
    assert result.memory_id is not None
    assert result.reasons == ()

    stored = gate.retrieve(
        RetrievalFilter(principal="research-agent", scope="team")
    )
    assert len(stored) == 1
    assert stored[0].lesson == lesson
    assert stored[0].principal == "research-agent"
    assert stored[0].scope == "team"
    assert stored[0].trace_id == "run-42"
    assert "pytest:passed" in stored[0].evidence


def test_reject_missing_governance_tags(gate: MemoryGate) -> None:
    traces = dual_traces("Some lesson")
    context = DistillContext(principal="", scope=MemoryScope.PRIVATE)

    result = gate.commit(traces, context)

    assert result.status is CommitStatus.REJECTED
    assert result.memory_id is None
    assert any("principal is required" in r for r in result.reasons)
    assert gate.store.count() == 0


def test_reject_empty_lesson(gate: MemoryGate) -> None:
    traces = dual_traces("   ")
    context = distill_context(principal="agent-a", scope="private")

    result = gate.commit(traces, context)

    assert result.rejected
    assert any("content must be non-empty" in r for r in result.reasons)


def test_reject_invalid_classification(gate: MemoryGate) -> None:
    traces = dual_traces("Valid text")
    context = distill_context(
        principal="agent-a",
        scope="private",
        classification="transcript_dump",
    )

    result = gate.commit(traces, context)

    assert result.rejected
    assert any("classification must be one of" in r for r in result.reasons)


def test_manual_review_returns_pending() -> None:
    gate = MemoryGate(
        store=InMemoryStore(),
        mode=GateMode.MANUAL_REVIEW,
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
    )
    traces = dual_traces("Awaiting human sign-off.")
    context = distill_context(principal="agent-a", scope=MemoryScope.SHARED)

    result = gate.commit(traces, context)

    assert result.pending
    assert result.pending_id is not None
    assert result.memory_id is None
    assert gate.store.count() == 0
    assert len(gate.list_pending()) == 1


def test_approve_pending_commits_to_store() -> None:
    gate = MemoryGate(
        store=InMemoryStore(),
        mode=GateMode.MANUAL_REVIEW,
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
    )
    traces = dual_traces("Promote after review.", metadata={"source": "backtest"})
    context = distill_context(
        principal="agent-a",
        scope=MemoryScope.TEAM,
        metadata={"source": "backtest"},
    )

    pending = gate.commit(traces, context)
    assert pending.pending_id is not None

    approved = gate.approve(pending.pending_id)

    assert approved.committed
    assert approved.memory_id is not None
    assert len(gate.list_pending()) == 0
    stored = gate.retrieve(RetrievalFilter(principal="agent-a", scope="team"))
    assert len(stored) == 1
    assert stored[0].metadata == {"source": "backtest"}


def test_list_pending_filters_by_principal_and_scope() -> None:
    gate = MemoryGate(
        store=InMemoryStore(),
        mode=GateMode.MANUAL_REVIEW,
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
    )
    gate.commit(
        dual_traces("Private hold"),
        distill_context(principal="agent-a", scope=MemoryScope.PRIVATE),
    )
    gate.commit(
        dual_traces("Team hold"),
        distill_context(principal="agent-a", scope=MemoryScope.TEAM),
    )
    gate.commit(
        dual_traces("Other agent"),
        distill_context(principal="agent-b", scope=MemoryScope.TEAM),
    )

    team_a = gate.list_pending(RetrievalFilter(principal="agent-a", scope="team"))
    assert len(team_a) == 1
    assert team_a[0].candidate.lesson == "Team hold"


def test_approve_unknown_pending_id_rejects() -> None:
    gate = MemoryGate(
        store=InMemoryStore(),
        mode=GateMode.MANUAL_REVIEW,
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
    )

    result = gate.approve("missing-id")

    assert result.rejected
    assert any("unknown pending_id" in r for r in result.reasons)


def test_readme_quick_start_flow() -> None:
    from verified_memory_gate import QuorumConfig, VerifierRegistry
    from verified_memory_gate.builtin_verifiers import (
        JsonSchemaVerifier,
        NumericToleranceVerifier,
        PytestExitCodeVerifier,
    )

    gate = MemoryGate.with_verifiers(
        VerifierRegistry(
            verifiers=(
                PytestExitCodeVerifier(),
                NumericToleranceVerifier(anchor="sharpe", expected=0.62, tolerance=0.05),
                JsonSchemaVerifier(
                    schema={
                        "type": "object",
                        "required": ("strategy_id",),
                        "properties": {"strategy_id": {"type": "string"}},
                    }
                ),
            ),
            quorum=QuorumConfig(min_passes=2),
        ),
        min_traces=1,
    )
    lesson = "Require Sharpe > 0.5 before promoting a strategy to paper trading."
    traces = dual_traces(
        lesson,
        trace_id="backtest-run-17",
        evidence=("metric:sharpe=0.62", "pytest:passed"),
        metadata={"strategy_id": "mom-v2"},
    )
    context = distill_context(
        principal="quant-research",
        scope=MemoryScope.TEAM,
        trace_id="backtest-run-17",
        metadata={"strategy_id": "mom-v2"},
    )

    result = gate.commit(traces, context)

    assert result.committed
    memories = gate.retrieve(RetrievalFilter(principal="quant-research", scope="team"))
    assert len(memories) == 1
    assert memories[0].lesson == lesson


def test_retrieve_filters_by_principal_and_scope(gate: MemoryGate) -> None:
    gate.commit(
        dual_traces("Private note"),
        distill_context(principal="agent-a", scope=MemoryScope.PRIVATE),
    )
    gate.commit(
        dual_traces("Team playbook"),
        distill_context(principal="agent-a", scope=MemoryScope.TEAM),
    )
    gate.commit(
        dual_traces("Other agent team note"),
        distill_context(principal="agent-b", scope=MemoryScope.TEAM),
    )

    team_a = gate.retrieve(RetrievalFilter(principal="agent-a", scope="team"))
    assert len(team_a) == 1
    assert team_a[0].lesson == "Team playbook"

    all_a = gate.retrieve(RetrievalFilter(principal="agent-a"))
    assert len(all_a) == 2


def test_validate_returns_all_errors(gate: MemoryGate) -> None:
    from verified_memory_gate import CandidateExperience

    candidate = CandidateExperience(
        lesson="",
        principal="",
        scope="",
        relationship="",
        classification="invalid",
    )

    errors = gate.validate(candidate)

    assert len(errors) >= 4
