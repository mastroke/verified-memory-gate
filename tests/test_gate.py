"""Tests for the memory write interceptor API (roadmap r1)."""

from __future__ import annotations

import pytest

from verified_memory_gate import (
    CandidateExperience,
    CommitStatus,
    GateMode,
    InMemoryStore,
    MemoryGate,
    MemoryScope,
    RetrievalFilter,
)


@pytest.fixture
def gate() -> MemoryGate:
    return MemoryGate(store=InMemoryStore())


def test_commit_valid_experience(gate: MemoryGate) -> None:
    candidate = CandidateExperience(
        lesson="Use walk-forward split with embargo for backtests.",
        principal="research-agent",
        scope=MemoryScope.TEAM,
        relationship="derived_from",
        classification="episodic",
        trace_id="run-42",
        evidence=("pytest:passed",),
    )

    result = gate.commit(candidate)

    assert result.status is CommitStatus.COMMITTED
    assert result.memory_id is not None
    assert result.reasons == ()

    stored = gate.retrieve(
        RetrievalFilter(principal="research-agent", scope="team")
    )
    assert len(stored) == 1
    assert stored[0].lesson == candidate.lesson
    assert stored[0].principal == "research-agent"
    assert stored[0].scope == "team"
    assert stored[0].trace_id == "run-42"
    assert stored[0].evidence == ("pytest:passed",)


def test_reject_missing_governance_tags(gate: MemoryGate) -> None:
    candidate = CandidateExperience(
        lesson="Some lesson",
        principal="",
        scope=MemoryScope.PRIVATE,
    )

    result = gate.commit(candidate)

    assert result.status is CommitStatus.REJECTED
    assert result.memory_id is None
    assert any("principal is required" in r for r in result.reasons)
    assert gate.store.count() == 0


def test_reject_empty_lesson(gate: MemoryGate) -> None:
    candidate = CandidateExperience(
        lesson="   ",
        principal="agent-a",
        scope="private",
    )

    result = gate.commit(candidate)

    assert result.rejected
    assert "lesson must be non-empty" in result.reasons


def test_reject_invalid_classification(gate: MemoryGate) -> None:
    candidate = CandidateExperience(
        lesson="Valid text",
        principal="agent-a",
        scope="private",
        classification="transcript_dump",
    )

    result = gate.commit(candidate)

    assert result.rejected
    assert any("classification must be one of" in r for r in result.reasons)


def test_manual_review_returns_pending() -> None:
    gate = MemoryGate(store=InMemoryStore(), mode=GateMode.MANUAL_REVIEW)
    candidate = CandidateExperience(
        lesson="Awaiting human sign-off.",
        principal="agent-a",
        scope=MemoryScope.SHARED,
    )

    result = gate.commit(candidate)

    assert result.pending
    assert result.pending_id is not None
    assert result.memory_id is None
    assert gate.store.count() == 0
    assert len(gate.list_pending()) == 1


def test_approve_pending_commits_to_store() -> None:
    gate = MemoryGate(store=InMemoryStore(), mode=GateMode.MANUAL_REVIEW)
    candidate = CandidateExperience(
        lesson="Promote after review.",
        principal="agent-a",
        scope=MemoryScope.TEAM,
        metadata={"source": "backtest"},
    )

    pending = gate.commit(candidate)
    assert pending.pending_id is not None

    approved = gate.approve(pending.pending_id)

    assert approved.committed
    assert approved.memory_id is not None
    assert len(gate.list_pending()) == 0
    stored = gate.retrieve(RetrievalFilter(principal="agent-a", scope="team"))
    assert len(stored) == 1
    assert stored[0].metadata == {"source": "backtest"}


def test_list_pending_filters_by_principal_and_scope() -> None:
    gate = MemoryGate(store=InMemoryStore(), mode=GateMode.MANUAL_REVIEW)
    gate.commit(
        CandidateExperience(
            lesson="Private hold",
            principal="agent-a",
            scope=MemoryScope.PRIVATE,
        )
    )
    gate.commit(
        CandidateExperience(
            lesson="Team hold",
            principal="agent-a",
            scope=MemoryScope.TEAM,
        )
    )
    gate.commit(
        CandidateExperience(
            lesson="Other agent",
            principal="agent-b",
            scope=MemoryScope.TEAM,
        )
    )

    team_a = gate.list_pending(RetrievalFilter(principal="agent-a", scope="team"))
    assert len(team_a) == 1
    assert team_a[0].candidate.lesson == "Team hold"


def test_approve_unknown_pending_id_rejects() -> None:
    gate = MemoryGate(store=InMemoryStore(), mode=GateMode.MANUAL_REVIEW)

    result = gate.approve("missing-id")

    assert result.rejected
    assert any("unknown pending_id" in r for r in result.reasons)


def test_readme_quick_start_flow() -> None:
    gate = MemoryGate()
    candidate = CandidateExperience(
        lesson="Require Sharpe > 0.5 before promoting a strategy to paper trading.",
        principal="quant-research",
        scope=MemoryScope.TEAM,
        relationship="derived_from",
        classification="episodic",
        trace_id="backtest-run-17",
        evidence=("metric:sharpe=0.62", "pytest:passed"),
    )

    result = gate.commit(candidate)

    assert result.committed
    memories = gate.retrieve(RetrievalFilter(principal="quant-research", scope="team"))
    assert len(memories) == 1
    assert memories[0].lesson == candidate.lesson


def test_retrieve_filters_by_principal_and_scope(gate: MemoryGate) -> None:
    gate.commit(
        CandidateExperience(
            lesson="Private note",
            principal="agent-a",
            scope=MemoryScope.PRIVATE,
        )
    )
    gate.commit(
        CandidateExperience(
            lesson="Team playbook",
            principal="agent-a",
            scope=MemoryScope.TEAM,
        )
    )
    gate.commit(
        CandidateExperience(
            lesson="Other agent team note",
            principal="agent-b",
            scope=MemoryScope.TEAM,
        )
    )

    team_a = gate.retrieve(RetrievalFilter(principal="agent-a", scope="team"))
    assert len(team_a) == 1
    assert team_a[0].lesson == "Team playbook"

    all_a = gate.retrieve(RetrievalFilter(principal="agent-a"))
    assert len(all_a) == 2


def test_validate_returns_all_errors(gate: MemoryGate) -> None:
    candidate = CandidateExperience(
        lesson="",
        principal="",
        scope="",
        relationship="",
        classification="invalid",
    )

    errors = gate.validate(candidate)

    assert len(errors) >= 4
