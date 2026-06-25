"""Pluggable verifier protocol, registry, and consensus quorum."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from verified_memory_gate.models import CandidateExperience


class VerifierOutcome(str, Enum):
    """Single-verifier evaluation result."""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class VerifierResult:
    """Outcome from one verifier against a candidate experience."""

    verifier: str
    outcome: VerifierOutcome
    reasons: tuple[str, ...] = ()

    @property
    def passed(self) -> bool:
        return self.outcome is VerifierOutcome.PASS

    @property
    def failed(self) -> bool:
        return self.outcome is VerifierOutcome.FAIL

    @property
    def skipped(self) -> bool:
        return self.outcome is VerifierOutcome.SKIP

    @classmethod
    def pass_(cls, verifier: str) -> VerifierResult:
        return cls(verifier=verifier, outcome=VerifierOutcome.PASS)

    @classmethod
    def fail(cls, verifier: str, *reasons: str) -> VerifierResult:
        return cls(verifier=verifier, outcome=VerifierOutcome.FAIL, reasons=reasons)

    @classmethod
    def skip(cls, verifier: str, *reasons: str) -> VerifierResult:
        return cls(verifier=verifier, outcome=VerifierOutcome.SKIP, reasons=reasons)


@dataclass(frozen=True, slots=True)
class QuorumConfig:
    """Minimum passing verifiers required for consensus."""

    min_passes: int = 1

    def __post_init__(self) -> None:
        if self.min_passes < 1:
            raise ValueError("min_passes must be at least 1")

    def reached(self, results: tuple[VerifierResult, ...]) -> bool:
        """Return True when enough non-skipped verifiers passed."""
        applicable = tuple(r for r in results if not r.skipped)
        if not applicable:
            return True
        passes = sum(1 for r in applicable if r.passed)
        return passes >= min(self.min_passes, len(applicable))


@dataclass(frozen=True, slots=True)
class ConsensusResult:
    """Aggregated outcome from the verifier registry."""

    passed: bool
    results: tuple[VerifierResult, ...]
    reasons: tuple[str, ...] = ()


@runtime_checkable
class Verifier(Protocol):
    """Domain-pluggable check run before a candidate memory write."""

    name: str

    def verify(self, candidate: CandidateExperience) -> VerifierResult:
        """Evaluate one candidate; return SKIP when not applicable."""
        ...


@dataclass
class VerifierRegistry:
    """Named verifier collection with configurable consensus quorum."""

    verifiers: tuple[Verifier, ...] = ()
    quorum: QuorumConfig = field(default_factory=QuorumConfig)

    def with_verifier(self, verifier: Verifier) -> VerifierRegistry:
        """Return a new registry with an additional verifier appended."""
        return VerifierRegistry(
            verifiers=self.verifiers + (verifier,),
            quorum=self.quorum,
        )

    def evaluate(self, candidate: CandidateExperience) -> ConsensusResult:
        """Run all verifiers and apply quorum rules."""
        if not self.verifiers:
            return ConsensusResult(passed=True, results=())

        results = tuple(v.verify(candidate) for v in self.verifiers)
        if self.quorum.reached(results):
            return ConsensusResult(passed=True, results=results)

        reasons: list[str] = []
        applicable = [r for r in results if not r.skipped]
        passes = sum(1 for r in applicable if r.passed)
        reasons.append(
            f"consensus quorum not met: {passes}/{len(applicable)} passed, "
            f"need {self.quorum.min_passes}"
        )
        for result in results:
            if result.failed:
                reasons.extend(
                    f"{result.verifier}: {reason}" for reason in result.reasons
                )
        return ConsensusResult(passed=False, results=results, reasons=tuple(reasons))
