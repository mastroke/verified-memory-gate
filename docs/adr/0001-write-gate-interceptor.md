# ADR 0001: Write gate interceptor as the persistence boundary

## Status

Accepted — 2026-06-25

## Context

Agent orchestrators increasingly write episodic lessons after each run. Without an explicit boundary, those writes bypass governance checks and verification — the failure modes documented in GateMem (access leakage, undeletable ghosts) and EDV (self-confirmation loops) compound silently.

Portfolio agent harnesses (quant research, memory-layer experiments) need a local, inspectable SDK that can evolve toward EDV verification and GateMem regression tests without adopting a hosted memory platform.

## Decision

Introduce `MemoryGate.commit()` as the **only supported write path** for v0.1:

1. Agents propose `CandidateExperience` records with mandatory governance tags: `principal`, `scope`, `relationship`, and `classification`.
2. The gate validates tags synchronously and returns one of three statuses: `committed`, `rejected`, or `pending`.
3. Persisted rows land in an `InMemoryStore` indexed by `principal` and `scope` for filtered retrieval.

Verification (pytest exit codes, numeric tolerance, JSON schema, consensus quorum) and tombstone deletion are deferred to later milestones but must plug into `commit()` without breaking the status contract.

## Consequences

**Positive**

- Clear seam between trajectory logging and durable memory; orchestrators can surface rejection reasons in agent state.
- Governance tags are enforced at write time, aligning with GateMem's access-isolation semantics before ACL read filters exist.
- In-memory store keeps the MVP runnable in CI with zero external services.

**Negative**

- No verification yet — valid tags alone commit, which is insufficient for production trust until r2–r3 land.
- In-memory storage is not durable; SQLite and vector-index tombstones follow in r4.
- `pending` is held in an in-memory inbox until `approve()` promotes the row; async verifier queues need explicit design in r3.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Direct vector-store writes from agents | No governance envelope; cannot gate policy regressions in CI |
| LLM-as-judge only | Grading-the-Grader shows brittle scoring on numeric/code outputs; domain-pluggable verifiers preferred |
| Hosted gate first | Conflicts with local-first, inspectable tooling goal; SDK must work offline |
