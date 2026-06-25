"""Write interceptor that validates governance tags before persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4

from verified_memory_gate.models import (
    CandidateExperience,
    CommitResult,
    CommitStatus,
    MemoryEntry,
    PendingCandidate,
    RetrievalFilter,
)
from verified_memory_gate.store import InMemoryStore
from verified_memory_gate.verifiers import VerifierRegistry

_VALID_CLASSIFICATIONS = frozenset({"episodic", "semantic", "procedural"})


class GateMode(str, Enum):
    """How the gate handles candidates that pass schema validation."""

    AUTO_COMMIT = "auto_commit"
    MANUAL_REVIEW = "manual_review"


@dataclass
class MemoryGate:
    """Intercept candidate memory writes and enforce governance before storage."""

    store: InMemoryStore | None = None
    mode: GateMode = GateMode.AUTO_COMMIT
    verifiers: VerifierRegistry | None = None
    _pending: dict[str, PendingCandidate] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.store is None:
            self.store = InMemoryStore()

    def validate(self, candidate: CandidateExperience) -> tuple[str, ...]:
        """Return validation error messages; empty tuple means valid."""
        errors: list[str] = []

        if not candidate.lesson or not candidate.lesson.strip():
            errors.append("lesson must be non-empty")

        if not candidate.principal or not candidate.principal.strip():
            errors.append("principal is required for governance tagging")

        scope = candidate.normalized_scope()
        if not scope:
            errors.append("scope is required for access isolation")

        if not candidate.relationship or not candidate.relationship.strip():
            errors.append("relationship tag is required")

        classification = candidate.classification.strip() if candidate.classification else ""
        if classification not in _VALID_CLASSIFICATIONS:
            errors.append(
                f"classification must be one of {sorted(_VALID_CLASSIFICATIONS)}"
            )

        return tuple(errors)

    def commit(self, candidate: CandidateExperience) -> CommitResult:
        """Attempt to persist a candidate experience through the write gate."""
        errors = self.validate(candidate)
        if errors:
            return CommitResult(status=CommitStatus.REJECTED, reasons=errors)

        if self.verifiers is not None:
            consensus = self.verifiers.evaluate(candidate)
            if not consensus.passed:
                return CommitResult(
                    status=CommitStatus.REJECTED,
                    reasons=consensus.reasons,
                )

        if self.mode is GateMode.MANUAL_REVIEW:
            pending_id = str(uuid4())
            self._pending[pending_id] = PendingCandidate(
                pending_id=pending_id,
                candidate=candidate,
            )
            return CommitResult(
                status=CommitStatus.PENDING,
                pending_id=pending_id,
                reasons=("awaiting manual review",),
            )

        entry = MemoryEntry.from_candidate(candidate)
        self.store.insert(entry)
        return CommitResult(status=CommitStatus.COMMITTED, memory_id=entry.memory_id)

    def list_pending(
        self, filters: RetrievalFilter | None = None
    ) -> list[PendingCandidate]:
        """Return inbox candidates awaiting manual approval."""
        items = list(self._pending.values())
        if filters is None:
            return items

        if filters.principal is not None:
            items = [p for p in items if p.candidate.principal == filters.principal]
        if filters.scope is not None:
            items = [
                p
                for p in items
                if p.candidate.normalized_scope() == filters.scope
            ]
        if filters.classification is not None:
            items = [
                p for p in items if p.candidate.classification == filters.classification
            ]
        return items

    def approve(self, pending_id: str) -> CommitResult:
        """Promote a pending candidate into committed storage."""
        pending = self._pending.pop(pending_id, None)
        if pending is None:
            return CommitResult(
                status=CommitStatus.REJECTED,
                reasons=(f"unknown pending_id: {pending_id}",),
            )

        entry = MemoryEntry.from_candidate(pending.candidate)
        self.store.insert(entry)
        return CommitResult(status=CommitStatus.COMMITTED, memory_id=entry.memory_id)

    def retrieve(self, filters: RetrievalFilter | None = None) -> list[MemoryEntry]:
        """List committed memories, optionally filtered by governance tags."""
        return self.store.list(filters)
