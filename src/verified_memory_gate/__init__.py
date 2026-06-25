"""Verified Memory Gate — governance and verification before agent memory writes."""

from verified_memory_gate.gate import GateMode, MemoryGate
from verified_memory_gate.models import (
    CandidateExperience,
    CommitResult,
    CommitStatus,
    MemoryEntry,
    MemoryScope,
    PendingCandidate,
    RetrievalFilter,
)
from verified_memory_gate.store import InMemoryStore
from verified_memory_gate.verifiers import (
    ConsensusResult,
    QuorumConfig,
    Verifier,
    VerifierOutcome,
    VerifierRegistry,
    VerifierResult,
)

__all__ = [
    "CandidateExperience",
    "CommitResult",
    "CommitStatus",
    "ConsensusResult",
    "GateMode",
    "InMemoryStore",
    "MemoryEntry",
    "MemoryGate",
    "MemoryScope",
    "PendingCandidate",
    "QuorumConfig",
    "RetrievalFilter",
    "Verifier",
    "VerifierOutcome",
    "VerifierRegistry",
    "VerifierResult",
]

__version__ = "0.1.0"
