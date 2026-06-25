"""Tests for verifier integration with MemoryGate.commit."""

from __future__ import annotations

from verified_memory_gate import (
    CommitStatus,
    DistillContext,
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
from tests.conftest import distill_context, dual_traces


def test_commit_rejects_when_verifier_quorum_fails() -> None:
    registry = VerifierRegistry(
        verifiers=(
            PytestExitCodeVerifier(),
            NumericToleranceVerifier(anchor="sharpe", expected=0.62, tolerance=0.01),
        ),
        quorum=QuorumConfig(min_passes=2),
    )
    gate = MemoryGate.with_verifiers(registry, store=InMemoryStore())
    traces = dual_traces(
        "Sharpe ratio only 0.40 on holdout.",
        evidence=("pytest:passed",),
    )
    context = distill_context(principal="quant-research", scope=MemoryScope.TEAM)

    result = gate.commit(traces, context)

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
    gate = MemoryGate.with_verifiers(registry, store=InMemoryStore())
    traces = dual_traces(
        "Sharpe ratio reached 0.60 on validation.",
        evidence=("pytest:passed",),
        metadata={"strategy_id": "mom-v2"},
    )
    context = distill_context(
        principal="quant-research",
        scope=MemoryScope.TEAM,
        metadata={"strategy_id": "mom-v2"},
    )

    result = gate.commit(traces, context)

    assert result.status is CommitStatus.COMMITTED
    assert gate.store.count() == 1


def test_commit_without_verifiers_skips_verify_stage() -> None:
    gate = MemoryGate(store=InMemoryStore())
    traces = dual_traces("No verifier attached.")
    context = DistillContext(
        principal="agent-a",
        scope=MemoryScope.PRIVATE,
    )

    result = gate.commit(traces, context)

    assert result.committed
    assert gate.store.count() == 1
