"""In-memory persistence with principal and scope indexing."""

from __future__ import annotations

from verified_memory_gate.models import MemoryEntry, RetrievalFilter


class InMemoryStore:
    """Thread-unsafe store for MVP development and unit tests."""

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}
        self._by_principal: dict[str, set[str]] = {}
        self._by_scope: dict[str, set[str]] = {}

    def insert(self, entry: MemoryEntry) -> MemoryEntry:
        self._entries[entry.memory_id] = entry
        self._by_principal.setdefault(entry.principal, set()).add(entry.memory_id)
        self._by_scope.setdefault(entry.scope, set()).add(entry.memory_id)
        return entry

    def get(self, memory_id: str) -> MemoryEntry | None:
        return self._entries.get(memory_id)

    def list(self, filters: RetrievalFilter | None = None) -> list[MemoryEntry]:
        if filters is None:
            return sorted(self._entries.values(), key=lambda e: e.created_at)

        candidate_ids: set[str] | None = None
        if filters.principal is not None:
            candidate_ids = set(self._by_principal.get(filters.principal, set()))
        if filters.scope is not None:
            scope_ids = self._by_scope.get(filters.scope, set())
            candidate_ids = scope_ids if candidate_ids is None else candidate_ids & scope_ids

        entries = (
            [self._entries[mid] for mid in candidate_ids]
            if candidate_ids is not None
            else list(self._entries.values())
        )

        if filters.classification is not None:
            entries = [e for e in entries if e.classification == filters.classification]

        return sorted(entries, key=lambda e: e.created_at)

    def count(self) -> int:
        return len(self._entries)

    def clear(self) -> None:
        self._entries.clear()
        self._by_principal.clear()
        self._by_scope.clear()
