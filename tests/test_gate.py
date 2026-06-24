"""Tests for the memory write interceptor API (roadmap r1)."""

from __future__ import annotations

import pytest

from verified_memory_gate import (
    CandidateExperience,
    CommitStatus,
    InMemoryStore,
    MemoryGate,
    MemoryScope,
    RetrievalFilter,
)
from verified_memory_gate.gate import GateMode


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
    assert result.memory_id is None
    assert gate.store.count() == 0


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
