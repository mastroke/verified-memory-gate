"""Append-only audit trail for memory writes, verifier outcomes, and deletions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from verified_memory_gate.models import (
    CandidateExperience,
    CommitResult,
    CommitStatus,
)
from verified_memory_gate.verifiers import ConsensusResult, VerifierOutcome


class AuditEventKind(str, Enum):
    """Categories recorded in the compliance audit log."""

    WRITE = "write"
    DELETION = "deletion"


@dataclass(frozen=True, slots=True)
class VerifierAudit:
    """One verifier outcome attached to a write audit record."""

    verifier: str
    outcome: VerifierOutcome

    def to_dict(self) -> dict[str, str]:
        return {"verifier": self.verifier, "outcome": self.outcome.value}


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Immutable audit row appended after a gate operation."""

    event_id: str
    occurred_at: datetime
    kind: AuditEventKind
    actor: str
    status: str | None = None
    memory_id: str | None = None
    pending_id: str | None = None
    trace_id: str | None = None
    scope: str | None = None
    verifiers: tuple[VerifierAudit, ...] = ()
    reasons: tuple[str, ...] = ()
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_id": self.event_id,
            "occurred_at": self.occurred_at.isoformat(),
            "kind": self.kind.value,
            "actor": self.actor,
            "success": self.success,
        }
        if self.status is not None:
            payload["status"] = self.status
        if self.memory_id is not None:
            payload["memory_id"] = self.memory_id
        if self.pending_id is not None:
            payload["pending_id"] = self.pending_id
        if self.trace_id is not None:
            payload["trace_id"] = self.trace_id
        if self.scope is not None:
            payload["scope"] = self.scope
        if self.verifiers:
            payload["verifiers"] = [item.to_dict() for item in self.verifiers]
        if self.reasons:
            payload["reasons"] = list(self.reasons)
        return payload


def _verifier_audits(consensus: ConsensusResult | None) -> tuple[VerifierAudit, ...]:
    if consensus is None:
        return ()
    return tuple(
        VerifierAudit(verifier=result.verifier, outcome=result.outcome)
        for result in consensus.results
    )


def build_write_record(
    *,
    actor: str,
    result: CommitResult,
    candidate: CandidateExperience | None,
    consensus: ConsensusResult | None,
) -> AuditRecord:
    """Build an append-only write audit row from a commit outcome."""
    trace_id = candidate.trace_id if candidate is not None else None
    scope = candidate.normalized_scope() if candidate is not None else None
    return AuditRecord(
        event_id=str(uuid4()),
        occurred_at=datetime.now(timezone.utc),
        kind=AuditEventKind.WRITE,
        actor=actor,
        status=result.status.value,
        memory_id=result.memory_id,
        pending_id=result.pending_id,
        trace_id=trace_id,
        scope=scope,
        verifiers=_verifier_audits(consensus),
        reasons=result.reasons,
        success=result.status is not CommitStatus.REJECTED,
    )


def build_deletion_record(
    *,
    actor: str,
    memory_id: str,
    success: bool,
    reasons: tuple[str, ...] = (),
) -> AuditRecord:
    """Build an append-only deletion audit row."""
    return AuditRecord(
        event_id=str(uuid4()),
        occurred_at=datetime.now(timezone.utc),
        kind=AuditEventKind.DELETION,
        actor=actor,
        memory_id=memory_id,
        success=success,
        reasons=reasons,
    )


@dataclass
class AppendOnlyAuditLog:
    """In-process append-only audit log for local daemon export."""

    _records: list[AuditRecord] = field(default_factory=list, repr=False)

    def append(self, record: AuditRecord) -> AuditRecord:
        """Append one immutable record; prior rows are never mutated."""
        self._records.append(record)
        return record

    def record_write(
        self,
        *,
        actor: str,
        result: CommitResult,
        candidate: CandidateExperience | None,
        consensus: ConsensusResult | None,
    ) -> AuditRecord:
        """Append a write attempt outcome with verifier details."""
        return self.append(
            build_write_record(
                actor=actor,
                result=result,
                candidate=candidate,
                consensus=consensus,
            )
        )

    def record_deletion(
        self,
        *,
        actor: str,
        memory_id: str,
        success: bool,
        reasons: tuple[str, ...] = (),
    ) -> AuditRecord:
        """Append a tombstone deletion event."""
        return self.append(
            build_deletion_record(
                actor=actor,
                memory_id=memory_id,
                success=success,
                reasons=reasons,
            )
        )

    def list(
        self,
        *,
        kind: AuditEventKind | None = None,
        actor: str | None = None,
    ) -> tuple[AuditRecord, ...]:
        """Return records in append order, optionally filtered."""
        items = self._records
        if kind is not None:
            items = [record for record in items if record.kind is kind]
        if actor is not None:
            items = [record for record in items if record.actor == actor]
        return tuple(items)

    def passed_verifiers(self, record: AuditRecord) -> tuple[str, ...]:
        """Return verifier names that passed for a write record."""
        return tuple(
            item.verifier
            for item in record.verifiers
            if item.outcome is VerifierOutcome.PASS
        )

    def count(self) -> int:
        return len(self._records)

    def export_records(self) -> list[dict[str, Any]]:
        """Return all records as JSON-serializable dicts for compliance review."""
        return [record.to_dict() for record in self._records]

    def export_json(self, *, indent: int | None = 2) -> str:
        """Serialize the full audit trail as a JSON array."""
        return json.dumps(self.export_records(), indent=indent)

    def export_ndjson(self) -> str:
        """Serialize the audit trail as newline-delimited JSON."""
        lines = [json.dumps(record.to_dict(), separators=(",", ":")) for record in self._records]
        return "\n".join(lines) + ("\n" if lines else "")


__all__ = [
    "AppendOnlyAuditLog",
    "AuditEventKind",
    "AuditRecord",
    "VerifierAudit",
    "build_deletion_record",
    "build_write_record",
]
