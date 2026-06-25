"""In-memory persistence with principal and scope indexing."""

from __future__ import annotations

from datetime import datetime, timezone

from verified_memory_gate.governance import passes_acl
from verified_memory_gate.models import MemoryEntry, RetrievalFilter, Tombstone


class InMemoryStore:
    """Thread-unsafe store for MVP development and unit tests."""

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}
        self._by_principal: dict[str, set[str]] = {}
        self._by_scope: dict[str, set[str]] = {}
        self._tombstones: dict[str, Tombstone] = {}
        self._embedding_index: dict[str, str] = {}

    def insert(self, entry: MemoryEntry) -> MemoryEntry:
        self._entries[entry.memory_id] = entry
        self._by_principal.setdefault(entry.principal, set()).add(entry.memory_id)
        self._by_scope.setdefault(entry.scope, set()).add(entry.memory_id)
        return entry

    def get(self, memory_id: str) -> MemoryEntry | None:
        if memory_id in self._tombstones:
            return None
        return self._entries.get(memory_id)

    def is_tombstoned(self, memory_id: str) -> bool:
        return memory_id in self._tombstones

    def tombstone(self, memory_id: str, principal: str) -> bool:
        """Mark a memory deleted and drop it from active and embedding indexes."""
        entry = self._entries.get(memory_id)
        if entry is None or memory_id in self._tombstones:
            return False
        if principal != entry.principal:
            return False

        self._tombstones[memory_id] = Tombstone(
            memory_id=memory_id,
            deleted_by=principal,
            deleted_at=datetime.now(timezone.utc),
        )
        self._by_principal.get(entry.principal, set()).discard(memory_id)
        self._by_scope.get(entry.scope, set()).discard(memory_id)
        self._embedding_index.pop(memory_id, None)
        return True

    def bind_embedding(self, memory_id: str, vector_id: str) -> bool:
        """Map a committed memory row to an external embedding index id."""
        if memory_id in self._tombstones or memory_id not in self._entries:
            return False
        self._embedding_index[memory_id] = vector_id
        return True

    def embedding_vector_id(self, memory_id: str) -> str | None:
        """Return the embedding id for *memory_id*, or None when tombstoned."""
        if memory_id in self._tombstones:
            return None
        return self._embedding_index.get(memory_id)

    def list(self, filters: RetrievalFilter | None = None) -> list[MemoryEntry]:
        if filters is None:
            entries = [
                entry
                for mid, entry in self._entries.items()
                if mid not in self._tombstones
            ]
            return sorted(entries, key=lambda e: e.created_at)

        candidate_ids: set[str] | None = None
        if filters.principal is not None:
            candidate_ids = set(self._by_principal.get(filters.principal, set()))
        if filters.scope is not None:
            scope_ids = self._by_scope.get(filters.scope, set())
            candidate_ids = scope_ids if candidate_ids is None else candidate_ids & scope_ids

        if candidate_ids is not None:
            entries = [
                self._entries[mid]
                for mid in candidate_ids
                if mid not in self._tombstones
            ]
        else:
            entries = [
                entry
                for mid, entry in self._entries.items()
                if mid not in self._tombstones
            ]

        if filters.classification is not None:
            entries = [e for e in entries if e.classification == filters.classification]

        entries = [e for e in entries if passes_acl(e, filters)]

        return sorted(entries, key=lambda e: e.created_at)

    def count(self) -> int:
        return len(self._entries) - len(self._tombstones)

    def clear(self) -> None:
        self._entries.clear()
        self._by_principal.clear()
        self._by_scope.clear()
        self._tombstones.clear()
        self._embedding_index.clear()
