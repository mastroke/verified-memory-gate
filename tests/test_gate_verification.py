"""Tests for verifier integration with MemoryGate.commit."""

from __future__ import annotations

from verified_memory_gate import (
    CandidateExperience,
    CommitStatus,
    MemoryGate,
    MemoryScope,
    QuorumConfig,
    VerifierRegistry,
)
from verified_memory_gate.builtin_verifiers import (
    JsonSchemaVerifier,
    NumericToleranceVerifier,
    PytestExitCodeVerifier,
)
from verified_memory_gate.store import InMemoryStore


def test_commit_rejects_when_verifier_quorum_fails() -> None:
    registry = VerifierRegistry(
        verifiers=(
            PytestExitCodeVerifier(),
            NumericToleranceVerifier(anchor="sharpe", expected=0.62, tolerance=0.01),
        ),
        quorum=QuorumConfig(min_passes=2),
    )
    gate = MemoryGate(store=InMemoryStore(), verifiers=registry)
    candidate = CandidateExperience(
        lesson="Sharpe ratio only 0.40 on holdout.",
        principal="quant-research",
        scope=MemoryScope.TEAM,
        evidence=("pytest:passed",),
    )

    result = gate.commit(candidate)

    assert result.status is CommitStatus.REJECTED
    assert any("quorum not met" in r for r in result.reasons)
    assert gate.store.count() == 0


def test_commit_passes_when_verifier_quorum_met() -> None:
    registry = VerifierRegistry(
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
    )
    gate = MemoryGate(store=InMemoryStore(), verifiers=registry)
    candidate = CandidateExperience(
        lesson="Sharpe ratio reached 0.60 on validation.",
        principal="quant-research",
        scope=MemoryScope.TEAM,
        evidence=("pytest:passed",),
        metadata={"strategy_id": "mom-v2"},
    )

    result = gate.commit(candidate)

    assert result.status is CommitStatus.COMMITTED
    assert gate.store.count() == 1


def test_commit_without_registry_skips_verification() -> None:
    gate = MemoryGate(store=InMemoryStore())
    candidate = CandidateExperience(
        lesson="No verifier attached.",
        principal="agent-a",
        scope=MemoryScope.PRIVATE,
    )

    result = gate.commit(candidate)

    assert result.committed
    assert gate.store.count() == 1
