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

__all__ = [
    "CandidateExperience",
    "CommitResult",
    "CommitStatus",
    "GateMode",
    "InMemoryStore",
    "MemoryEntry",
    "MemoryGate",
    "MemoryScope",
    "PendingCandidate",
    "RetrievalFilter",
]

__version__ = "0.1.0"
