"""Tests for in-memory store indexing."""

from __future__ import annotations

from verified_memory_gate.models import MemoryEntry, RetrievalFilter
from verified_memory_gate.store import InMemoryStore


def _entry(
    *,
    memory_id: str,
    principal: str,
    scope: str,
    classification: str = "episodic",
) -> MemoryEntry:
    from datetime import datetime, timezone

    return MemoryEntry(
        memory_id=memory_id,
        lesson=f"lesson-{memory_id}",
        principal=principal,
        scope=scope,
        relationship="self",
        classification=classification,
        trace_id=None,
        evidence=(),
        metadata={},
        created_at=datetime.now(timezone.utc),
    )


def test_store_indexes_and_filters() -> None:
    store = InMemoryStore()
    store.insert(_entry(memory_id="1", principal="p1", scope="private"))
    store.insert(_entry(memory_id="2", principal="p1", scope="team"))
    store.insert(
        _entry(memory_id="3", principal="p2", scope="team", classification="semantic")
    )

    assert store.count() == 3
    assert len(store.list(RetrievalFilter(scope="team"))) == 2
    assert len(store.list(RetrievalFilter(classification="semantic"))) == 1

    store.clear()
    assert store.count() == 0
