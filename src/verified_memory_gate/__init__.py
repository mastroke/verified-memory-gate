"""Verified Memory Gate — governance and verification before agent memory writes."""

from verified_memory_gate.gate import MemoryGate
from verified_memory_gate.models import (
    CandidateExperience,
    CommitResult,
    CommitStatus,
    MemoryEntry,
    MemoryScope,
    RetrievalFilter,
)
from verified_memory_gate.store import InMemoryStore

__all__ = [
    "CandidateExperience",
    "CommitResult",
    "CommitStatus",
    "InMemoryStore",
    "MemoryEntry",
    "MemoryGate",
    "MemoryScope",
    "RetrievalFilter",
]

__version__ = "0.1.0"
