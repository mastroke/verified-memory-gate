"""Tests for append-only audit trail (roadmap r7)."""

from __future__ import annotations

import json

import pytest

from verified_memory_gate import (
    AppendOnlyAuditLog,
    AuditEventKind,
    CommitStatus,
    GateMode,
    InMemoryStore,
    MemoryGate,
    MemoryScope,
    QuorumConfig,
    VerifierRegistry,
)
from verified_memory_gate.builtin_verifiers import PytestExitCodeVerifier
from verified_memory_gate.models import CommitResult
from verified_memory_gate.verifiers import VerifierOutcome, VerifierResult
from tests.conftest import distill_context, dual_traces, gate  # noqa: F401


def test_append_only_audit_log_records_writes_in_order() -> None:
    log = AppendOnlyAuditLog()
    first = log.record_write(
        actor="agent-a",
        result=CommitResult(status=CommitStatus.COMMITTED, memory_id="mem-1"),
        candidate=None,
        consensus=None,
    )
    second = log.record_deletion(actor="agent-a", memory_id="mem-1", success=True)

    assert log.count() == 2
    assert log.list()[0].event_id == first.event_id
    assert log.list()[1].event_id == second.event_id
    assert log.list(kind=AuditEventKind.DELETION)[0].memory_id == "mem-1"


def test_export_json_and_ndjson_for_compliance_review() -> None:
    log = AppendOnlyAuditLog()
    log.record_write(
        actor="quant-research",
        result=CommitResult(status=CommitStatus.REJECTED, reasons=("verify failed",)),
        candidate=None,
        consensus=None,
    )

    payload = json.loads(log.export_json())
    assert len(payload) == 1
    assert payload[0]["actor"] == "quant-research"
    assert payload[0]["status"] == "rejected"

    lines = log.export_ndjson().strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["kind"] == "write"


def test_gate_commit_appends_verifier_outcomes_to_audit_log(gate: MemoryGate) -> None:
    audit = AppendOnlyAuditLog()
    verifiers = VerifierRegistry(
        verifiers=(PytestExitCodeVerifier(),),
        quorum=QuorumConfig(min_passes=1),
    )
    audited_gate = MemoryGate.with_verifiers(
        verifiers,
        store=InMemoryStore(),
        execute=gate.pipeline.execute,
    )
    audited_gate.audit_log = audit

    lesson = "Gate eval release on regression threshold."
    traces = dual_traces(lesson, evidence=("pytest:passed",))
    context = distill_context(principal="quant-research", scope=MemoryScope.TEAM)

    result = audited_gate.commit(traces, context)

    assert result.committed
    assert audit.count() == 1
    record = audit.list()[0]
    assert record.actor == "quant-research"
    assert record.status == "committed"
    assert audit.passed_verifiers(record) == ("pytest_exit_code",)


def test_gate_forget_appends_deletion_event(gate: MemoryGate) -> None:
    audit = AppendOnlyAuditLog()
    gate.audit_log = audit
    lesson = "Sharpe gate before paper trading."
    traces = dual_traces(lesson)
    context = distill_context(principal="quant-research", scope=MemoryScope.PRIVATE)
    committed = gate.commit(traces, context)
    assert committed.memory_id is not None

    assert gate.forget(committed.memory_id, "quant-research") is True
    assert audit.count() == 2
    deletion = audit.list(kind=AuditEventKind.DELETION)[0]
    assert deletion.success is True
    assert deletion.memory_id == committed.memory_id


def test_manual_review_and_approve_emit_write_audit_rows(gate: MemoryGate) -> None:
    audit = AppendOnlyAuditLog()
    gate.audit_log = audit
    gate.mode = GateMode.MANUAL_REVIEW
    traces = dual_traces("Awaiting human approval.")
    context = distill_context(principal="review-agent", scope=MemoryScope.TEAM)

    pending = gate.commit(traces, context)
    assert pending.pending
    assert audit.list()[0].status == "pending"

    approved = gate.approve(pending.pending_id or "")
    assert approved.committed
    assert audit.count() == 2
    assert audit.list()[1].status == "committed"


def test_rejected_commit_records_verifier_failures() -> None:
    audit = AppendOnlyAuditLog()

    class AlwaysFail:
        name = "always_fail"

        def verify(self, candidate: object) -> VerifierResult:
            return VerifierResult.fail(self.name, "forced failure")

    gate = MemoryGate.with_verifiers(
        VerifierRegistry(verifiers=(AlwaysFail(),), quorum=QuorumConfig(min_passes=1)),
        store=InMemoryStore(),
        min_traces=1,
    )
    gate.audit_log = audit
    traces = dual_traces("This should not commit.")
    context = distill_context(principal="agent-a", scope=MemoryScope.PRIVATE)

    result = gate.commit(traces, context)

    assert result.rejected
    record = audit.list()[0]
    assert record.success is False
    assert record.verifiers[0].outcome is VerifierOutcome.FAIL
