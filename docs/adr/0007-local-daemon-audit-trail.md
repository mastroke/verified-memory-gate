# ADR 0007: Local daemon and append-only audit trail

## Status

Accepted — 2026-06-26

## Context

Milestones r1–r6 enforce write-time verification, read ACL, regression harness,
and LangGraph hooks, but operators still lack a durable, inspectable record of
who attempted writes, which verifiers passed, and when memories were tombstoned.
Hosted audit tiers are out of scope for the open-core SDK; a local append-only
log plus export path is the minimum credible compliance surface.

## Decision

1. **`AppendOnlyAuditLog`** — in-process store of immutable `AuditRecord` rows.
   Writes capture principal, commit status, verifier outcomes, and rejection
   reasons. Deletions capture actor, memory id, and success flag. Rows are never
   updated or removed in memory.
2. **`MemoryGate.audit_log`** — optional hook that records on `commit()`,
   `approve()`, and `forget()`. Gates without an audit log behave as before.
3. **Compliance export** — `export_json()` and `export_ndjson()` serialize the
   full trail for offline review; no mutation APIs on the log.
4. **Optional FastAPI daemon** — `create_app()` serves `/health`, `/audit`,
   `/audit/export`, and read-only `/memories`. Installed via the `daemon` extra;
   `vmg-audit-daemon` runs uvicorn on `127.0.0.1:8765`.

## Consequences

**Positive**

- Audit is orthogonal to storage: same gate API with an attached log.
- Export formats map directly to compliance tooling (JSON array or NDJSON stream).
- FastAPI remains optional; core library tests do not require HTTP deps unless
  daemon tests run.

**Negative**

- In-process log is not durable across process restarts; file or SQLite backends
  belong to a future hosted tier.
- `approve()` re-audit rows omit verifier consensus (already evaluated at pending
  time); full verify replay is intentionally deferred.
- Daemon binds localhost only; TLS and auth are operator concerns.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Mutating audit rows on correction | Violates append-only compliance semantics |
| Mandatory FastAPI dependency | Bloats SDK install for library-only users |
| Log only successful commits | Rejected writes and failed deletions are audit-relevant |
