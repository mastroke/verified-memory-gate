"""Tests for verifier protocol, registry, and quorum consensus."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from verified_memory_gate.models import CandidateExperience, MemoryScope
from verified_memory_gate.verifiers import (
    ConsensusResult,
    QuorumConfig,
    Verifier,
    VerifierOutcome,
    VerifierRegistry,
    VerifierResult,
)


@dataclass(frozen=True)
class _StubVerifier:
    name: str
    outcome: VerifierOutcome
    reasons: tuple[str, ...] = ()

    def verify(self, candidate: CandidateExperience) -> VerifierResult:
        return VerifierResult(
            verifier=self.name,
            outcome=self.outcome,
            reasons=self.reasons,
        )


def _candidate() -> CandidateExperience:
    return CandidateExperience(
        lesson="Example lesson.",
        principal="agent-a",
        scope=MemoryScope.PRIVATE,
    )


def test_empty_registry_passes_by_default() -> None:
    registry = VerifierRegistry()
    result = registry.evaluate(_candidate())

    assert isinstance(result, ConsensusResult)
    assert result.passed
    assert result.results == ()


def test_single_passing_verifier_meets_quorum() -> None:
    registry = VerifierRegistry(
        verifiers=(_StubVerifier("a", VerifierOutcome.PASS),),
        quorum=QuorumConfig(min_passes=1),
    )

    result = registry.evaluate(_candidate())

    assert result.passed
    assert len(result.results) == 1
    assert result.results[0].passed


def test_quorum_requires_minimum_passes() -> None:
    registry = VerifierRegistry(
        verifiers=(
            _StubVerifier("a", VerifierOutcome.PASS),
            _StubVerifier("b", VerifierOutcome.FAIL, ("bad metric",)),
            _StubVerifier("c", VerifierOutcome.PASS),
        ),
        quorum=QuorumConfig(min_passes=2),
    )

    result = registry.evaluate(_candidate())

    assert result.passed


def test_quorum_failure_collects_reasons() -> None:
    registry = VerifierRegistry(
        verifiers=(
            _StubVerifier("pytest", VerifierOutcome.FAIL, ("exit code 1",)),
            _StubVerifier("schema", VerifierOutcome.FAIL, ("missing field",)),
        ),
        quorum=QuorumConfig(min_passes=2),
    )

    result = registry.evaluate(_candidate())

    assert not result.passed
    assert any("quorum not met" in r for r in result.reasons)
    assert any("pytest: exit code 1" in r for r in result.reasons)


def test_skipped_verifiers_do_not_count_toward_quorum_denominator() -> None:
    registry = VerifierRegistry(
        verifiers=(
            _StubVerifier("optional", VerifierOutcome.SKIP, ("not applicable",)),
            _StubVerifier("required", VerifierOutcome.PASS),
        ),
        quorum=QuorumConfig(min_passes=1),
    )

    result = registry.evaluate(_candidate())

    assert result.passed


def test_all_skipped_verifiers_pass_consensus() -> None:
    registry = VerifierRegistry(
        verifiers=(_StubVerifier("optional", VerifierOutcome.SKIP),),
        quorum=QuorumConfig(min_passes=1),
    )

    result = registry.evaluate(_candidate())

    assert result.passed


def test_with_verifier_returns_new_registry() -> None:
    base = VerifierRegistry()
    extended = base.with_verifier(_StubVerifier("a", VerifierOutcome.PASS))

    assert base.verifiers == ()
    assert len(extended.verifiers) == 1


def test_quorum_config_rejects_zero_min_passes() -> None:
    with pytest.raises(ValueError, match="min_passes"):
        QuorumConfig(min_passes=0)


def test_verifier_is_runtime_checkable() -> None:
    stub = _StubVerifier("a", VerifierOutcome.PASS)
    assert isinstance(stub, Verifier)
