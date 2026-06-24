"""Core schemas for candidate experiences and commit outcomes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class CommitStatus(str, Enum):
    """Outcome of a write-gate commit attempt."""

    PENDING = "pending"
    REJECTED = "rejected"
    COMMITTED = "committed"


class MemoryScope(str, Enum):
    """GateMem-aligned scope labels for memory isolation."""

    PRIVATE = "private"
    TEAM = "team"
    SHARED = "shared"


@dataclass(frozen=True, slots=True)
class CandidateExperience:
    """Structured lesson proposed by an agent executor before persistence."""

    lesson: str
    principal: str
    scope: MemoryScope | str
    relationship: str = "self"
    classification: str = "episodic"
    trace_id: str | None = None
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def normalized_scope(self) -> str:
        if isinstance(self.scope, MemoryScope):
            return self.scope.value
        return str(self.scope)


@dataclass(frozen=True, slots=True)
class CommitResult:
    """Result returned by ``MemoryGate.commit``."""

    status: CommitStatus
    memory_id: str | None = None
    reasons: tuple[str, ...] = ()

    @property
    def committed(self) -> bool:
        return self.status is CommitStatus.COMMITTED

    @property
    def rejected(self) -> bool:
        return self.status is CommitStatus.REJECTED

    @property
    def pending(self) -> bool:
        return self.status is CommitStatus.PENDING


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """Persisted memory row after a successful gate commit."""

    memory_id: str
    lesson: str
    principal: str
    scope: str
    relationship: str
    classification: str
    trace_id: str | None
    evidence: tuple[str, ...]
    metadata: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_candidate(cls, candidate: CandidateExperience) -> MemoryEntry:
        return cls(
            memory_id=str(uuid4()),
            lesson=candidate.lesson.strip(),
            principal=candidate.principal.strip(),
            scope=candidate.normalized_scope(),
            relationship=candidate.relationship.strip(),
            classification=candidate.classification.strip(),
            trace_id=candidate.trace_id,
            evidence=candidate.evidence,
            metadata=dict(candidate.metadata),
            created_at=datetime.now(timezone.utc),
        )


@dataclass(frozen=True, slots=True)
class RetrievalFilter:
    """Read-side filter aligned with governance envelope tags."""

    principal: str | None = None
    scope: str | None = None
    classification: str | None = None
