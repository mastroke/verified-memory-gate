"""GateMem-aligned read ACL and leak-target checks."""

from __future__ import annotations

from typing import Any

from verified_memory_gate.models import MemoryEntry, MemoryScope, RetrievalFilter

_SCOPE_PRIVATE = MemoryScope.PRIVATE.value
_SCOPE_TEAM = MemoryScope.TEAM.value
_SCOPE_SHARED = MemoryScope.SHARED.value


def parse_leak_targets(metadata: dict[str, Any]) -> tuple[str, ...]:
    """Return protected entity markers from governance metadata."""
    raw = metadata.get("leak_targets")
    if raw is None:
        return ()
    if isinstance(raw, str):
        return (raw,) if raw else ()
    return tuple(str(item) for item in raw if str(item))


def effective_requester(filters: RetrievalFilter) -> str | None:
    """Resolve the principal performing the read for ACL enforcement."""
    if filters.requester is not None:
        return filters.requester
    return filters.principal


def _delegates(entry: MemoryEntry) -> frozenset[str]:
    raw = entry.metadata.get("delegates", ())
    if isinstance(raw, str):
        return frozenset({raw}) if raw else frozenset()
    return frozenset(str(item) for item in raw)


def _allowed_relationships(entry: MemoryEntry) -> frozenset[str]:
    raw = entry.metadata.get("allowed_relationships", ())
    if isinstance(raw, str):
        return frozenset({raw}) if raw else frozenset()
    return frozenset(str(item) for item in raw)


def _leak_target_authorized(
    requester: str,
    entry: MemoryEntry,
    relationship: str | None,
) -> bool:
    """Whether *requester* may see entries tagged with protected leak targets."""
    leak_targets = parse_leak_targets(entry.metadata)
    if not leak_targets:
        return True
    if requester == entry.principal:
        return True
    if requester in _delegates(entry):
        return True
    if relationship is not None and relationship in _allowed_relationships(entry):
        return True
    return False


def can_read(
    requester: str,
    entry: MemoryEntry,
    *,
    relationship: str | None = None,
    team_id: str | None = None,
) -> bool:
    """Return True when *requester* is authorized to retrieve *entry*."""
    if requester == entry.principal:
        return _leak_target_authorized(requester, entry, relationship)

    scope = entry.scope
    if scope == _SCOPE_PRIVATE:
        return False

    if scope == _SCOPE_SHARED:
        return _leak_target_authorized(requester, entry, relationship)

    if scope == _SCOPE_TEAM:
        entry_team = entry.metadata.get("team_id")
        if (
            entry_team is not None
            and team_id is not None
            and str(entry_team) == team_id
        ):
            return _leak_target_authorized(requester, entry, relationship)
        if requester in _delegates(entry):
            return _leak_target_authorized(requester, entry, relationship)
        if relationship is not None and relationship in _allowed_relationships(entry):
            return _leak_target_authorized(requester, entry, relationship)
        return False

    return False


def passes_acl(entry: MemoryEntry, filters: RetrievalFilter) -> bool:
    """Apply retrieval ACL when a requester can be resolved from *filters*."""
    requester = effective_requester(filters)
    if requester is None:
        return True
    return can_read(
        requester,
        entry,
        relationship=filters.relationship,
        team_id=filters.team_id,
    )
