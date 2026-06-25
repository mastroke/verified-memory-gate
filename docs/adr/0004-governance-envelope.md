# ADR 0004: Governance envelope for read ACL and tombstones

## Status

Accepted — 2026-06-25

## Context

GateMem evaluates multi-principal shared memory on utility, access control, and active forgetting. Milestones r1–r3 enforced governance tags and EDV verification at write time, but reads still indexed only by tag intersection — an unauthorized requester could query another principal's private rows if it knew the owner id. Vector backends also retain embedding mappings after logical deletion, producing recoverable ghosts in retrieval.

## Decision

Add a governance envelope around `InMemoryStore.list()` and `MemoryGate.retrieve()`:

1. **Principal-scoped read ACL** — `RetrievalFilter` carries an explicit `requester` (defaulting to `principal` when set). `can_read()` enforces scope rules: `private` is owner-only; `team` allows same `team_id` or delegated principals/relationships; `shared` is open unless leak targets apply.
2. **Leak-target metadata** — Protected entities live in `metadata["leak_targets"]`. Entries with leak targets require owner, delegate, or `allowed_relationships` match even when scope would otherwise permit access.
3. **Tombstone deletion** — `MemoryGate.forget()` marks rows deleted, drops them from principal/scope indexes, and clears the embedding-index mapping so retrieval and vector lookup both return empty.

## Consequences

**Positive**

- Read path aligns with GateMem access-control and active-forgetting probes before the r5 harness lands.
- Embedding propagation gives a single deletion seam for future pgvector or Mem0 adapters.
- ACL is pure functions in `governance.py`, testable without a running gate.

**Negative**

- Team membership is a string `team_id` in metadata, not a full principal registry — sufficient for MVP fixtures, not institutional SSO.
- Tombstones retain the row for audit but hide it from `get()`; durable backends may choose physical erase later.
- No automatic leak-target redaction in lesson text — retrieval excludes whole rows; answer-time redaction stays with the agent layer.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Post-retrieval LLM policy only | GateMem shows retrieval leakage even when the model is prompted to refuse |
| Hard-delete rows on forget | Loses audit trail; benchmark checks interface-level non-recovery, not crypto erase |
| Scope-only filters without requester | Cannot block cross-principal private reads |
