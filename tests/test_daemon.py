"""Tests for optional FastAPI audit daemon (roadmap r7)."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from verified_memory_gate import (
    AppendOnlyAuditLog,
    AuditEventKind,
    InMemoryStore,
    MemoryGate,
    MemoryScope,
)
from verified_memory_gate.daemon import create_app
from tests.conftest import distill_context, dual_traces


def _client(gate: MemoryGate, audit: AppendOnlyAuditLog) -> TestClient:
    return TestClient(create_app(gate=gate, audit_log=audit))


def test_health_endpoint() -> None:
    audit = AppendOnlyAuditLog()
    gate = MemoryGate(store=InMemoryStore(), audit_log=audit)
    response = _client(gate, audit).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_audit_export_json_after_commit() -> None:
    audit = AppendOnlyAuditLog()
    gate = MemoryGate(store=InMemoryStore(), audit_log=audit)
    client = _client(gate, audit)

    traces = dual_traces("Audit daemon export check.")
    context = distill_context(principal="compliance", scope=MemoryScope.TEAM)
    gate.commit(traces, context)

    response = client.get("/audit/export")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["actor"] == "compliance"
    assert payload[0]["kind"] == AuditEventKind.WRITE.value


def test_audit_export_ndjson() -> None:
    audit = AppendOnlyAuditLog()
    gate = MemoryGate(store=InMemoryStore(), audit_log=audit)
    client = _client(gate, audit)

    traces = dual_traces("NDJSON export row.")
    context = distill_context(principal="compliance", scope=MemoryScope.PRIVATE)
    gate.commit(traces, context)

    response = client.get("/audit/export?format=ndjson")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    lines = response.text.strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["actor"] == "compliance"


def test_list_audit_filters_by_kind() -> None:
    audit = AppendOnlyAuditLog()
    gate = MemoryGate(store=InMemoryStore(), audit_log=audit)
    client = _client(gate, audit)

    traces = dual_traces("Deletion audit row.")
    context = distill_context(principal="owner", scope=MemoryScope.PRIVATE)
    committed = gate.commit(traces, context)
    assert committed.memory_id is not None
    gate.forget(committed.memory_id, "owner")

    response = client.get("/audit", params={"kind": AuditEventKind.DELETION.value})
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["records"][0]["kind"] == "deletion"
