"""Tests for governance envelope: ACL, tombstones, leak targets (roadmap r4)."""

from __future__ import annotations

from datetime import datetime, timezone

from verified_memory_gate import (
    DistillContext,
    EDVPipeline,
    ExecuteStage,
    InMemoryStore,
    MemoryGate,
    MemoryScope,
    RetrievalFilter,
)
from verified_memory_gate.governance import can_read, parse_leak_targets
from verified_memory_gate.models import MemoryEntry
from tests.conftest import distill_context, dual_traces, gate  # noqa: F401


def _entry(
    *,
    memory_id: str = "m1",
    principal: str = "agent-a",
    scope: str = "private",
    metadata: dict | None = None,
) -> MemoryEntry:
    return MemoryEntry(
        memory_id=memory_id,
        lesson="protected lesson",
        principal=principal,
        scope=scope,
        relationship="self",
        classification="episodic",
        trace_id=None,
        evidence=(),
        metadata=dict(metadata or {}),
        created_at=datetime.now(timezone.utc),
    )


def test_private_scope_denies_cross_principal_read() -> None:
    store = InMemoryStore()
    store.insert(_entry(memory_id="p1", principal="agent-a", scope="private"))

    leaked = store.list(
        RetrievalFilter(requester="agent-b", principal="agent-a", scope="private")
    )
    assert leaked == []

    owner = store.list(
        RetrievalFilter(requester="agent-a", principal="agent-a", scope="private")
    )
    assert len(owner) == 1


def test_team_scope_allows_same_team_id() -> None:
    store = InMemoryStore()
    store.insert(
        _entry(
            memory_id="t1",
            principal="agent-a",
            scope="team",
            metadata={"team_id": "desk-1"},
        )
    )

    peer = store.list(
        RetrievalFilter(
            requester="agent-b",
            scope="team",
            team_id="desk-1",
        )
    )
    assert len(peer) == 1

    outsider = store.list(
        RetrievalFilter(
            requester="agent-c",
            scope="team",
            team_id="desk-2",
        )
    )
    assert outsider == []


def test_leak_targets_block_team_peer_without_delegation() -> None:
    store = InMemoryStore()
    store.insert(
        _entry(
            memory_id="lt1",
            principal="agent-a",
            scope="team",
            metadata={
                "team_id": "desk-1",
                "leak_targets": ("patient_mrn",),
            },
        )
    )

    peer = store.list(
        RetrievalFilter(
            requester="agent-b",
            scope="team",
            team_id="desk-1",
        )
    )
    assert peer == []

    store.insert(
        _entry(
            memory_id="lt2",
            principal="agent-a",
            scope="team",
            metadata={
                "team_id": "desk-1",
                "leak_targets": ("patient_mrn",),
                "allowed_relationships": ("assigned_nurse",),
            },
        )
    )
    nurse = store.list(
        RetrievalFilter(
            requester="agent-b",
            scope="team",
            team_id="desk-1",
            relationship="assigned_nurse",
        )
    )
    assert len(nurse) == 1


def test_shared_scope_readable_with_leak_target_delegation() -> None:
    entry = _entry(
        principal="agent-a",
        scope="shared",
        metadata={"leak_targets": ("ssn",), "delegates": ("agent-b",)},
    )
    assert can_read("agent-c", entry) is False
    assert can_read("agent-b", entry) is True


def test_parse_leak_targets_normalizes_metadata() -> None:
    assert parse_leak_targets({}) == ()
    assert parse_leak_targets({"leak_targets": "mrn"}) == ("mrn",)
    assert parse_leak_targets({"leak_targets": ("a", "b")}) == ("a", "b")


def test_tombstone_removes_from_retrieval_and_embedding_index() -> None:
    gate = MemoryGate(
        store=InMemoryStore(),
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
    )
    result = gate.commit(
        dual_traces("Delete me after review."),
        distill_context(principal="agent-a", scope=MemoryScope.TEAM),
    )
    assert result.memory_id is not None
    memory_id = result.memory_id

    assert gate.bind_embedding(memory_id, "vec-42") is True
    assert gate.embedding_vector_id(memory_id) == "vec-42"

    assert gate.forget(memory_id, "agent-a") is True
    assert gate.embedding_vector_id(memory_id) is None
    assert gate.retrieve(RetrievalFilter(principal="agent-a", scope="team")) == []
    assert gate.store.get(memory_id) is None
    assert gate.store.is_tombstoned(memory_id) is True


def test_forget_rejects_non_owner() -> None:
    gate = MemoryGate(
        store=InMemoryStore(),
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
    )
    result = gate.commit(
        dual_traces("Owner only deletion."),
        distill_context(principal="agent-a", scope=MemoryScope.PRIVATE),
    )
    assert result.memory_id is not None

    assert gate.forget(result.memory_id, "agent-b") is False
    assert len(gate.retrieve(RetrievalFilter(principal="agent-a", scope="private"))) == 1


def test_bind_embedding_rejects_tombstoned_memory() -> None:
    store = InMemoryStore()
    store.insert(_entry(memory_id="gone"))
    store.bind_embedding("gone", "vec-1")
    assert store.tombstone("gone", "agent-a") is True
    assert store.bind_embedding("gone", "vec-2") is False
    assert store.embedding_vector_id("gone") is None


def test_retrieve_infers_requester_from_principal_filter(gate: MemoryGate) -> None:
    gate.commit(
        dual_traces("Private note"),
        distill_context(principal="agent-a", scope=MemoryScope.PRIVATE),
    )
    gate.commit(
        dual_traces("Team playbook"),
        distill_context(principal="agent-a", scope=MemoryScope.TEAM),
    )

    team_a = gate.retrieve(RetrievalFilter(principal="agent-a", scope="team"))
    assert len(team_a) == 1
    assert team_a[0].lesson == "Team playbook"
