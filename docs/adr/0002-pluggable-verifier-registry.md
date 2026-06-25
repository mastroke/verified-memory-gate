# ADR 0002: Pluggable verifier registry with consensus quorum

## Status

Accepted — 2026-06-25

## Context

ADR 0001 deferred write-time verification to keep the v0.1 interceptor small. Research on EDV and Grading-the-Grader shows that memory inserts need heterogeneous, domain-pluggable checks — pytest exit codes, anchored numeric tolerance, and structured schema validation — rather than a single LLM judge.

Orchestrators (quant research, data-analysis agents) already attach evidence strings and metadata to candidate lessons. The gate must evaluate those signals synchronously at `commit()` without changing the three-status contract (`committed`, `rejected`, `pending`).

## Decision

1. Define a `Verifier` protocol returning `VerifierResult` with outcomes `pass`, `fail`, or `skip`.
2. Aggregate verifiers in a `VerifierRegistry` with `QuorumConfig.min_passes` for consensus.
3. Ship builtins:
   - `PytestExitCodeVerifier` — reads `pytest:passed` evidence or `metadata.pytest_exit_code == 0`.
   - `NumericToleranceVerifier` — anchor-extracts numbers from lesson/evidence/metadata and compares within tolerance (Grading-the-Grader-style parsing).
   - `JsonSchemaVerifier` — validates a candidate field against a minimal JSON-schema subset with no extra dependencies.
4. `MemoryGate` accepts an optional `verifiers` registry. After governance validation, consensus failure returns `rejected` with aggregated reasons.

Skipped verifiers do not count toward the quorum denominator. An empty registry or all-skipped results pass by default so existing callers remain unchanged.

## Consequences

**Positive**

- Verification is composable and testable in isolation; orchestrators pick checks per domain.
- Quorum config supports layered consensus without hard-coding “all must pass”.
- Anchor-based numeric parsing reduces false rejects on natural-language agent output.

**Negative**

- JSON schema support is intentionally minimal; complex schemas need an external validator wired as a custom `Verifier`.
- Synchronous evaluation only; async verifier queues remain for r3 (EDV pipeline).
- Skipped verifiers can mask missing evidence if quorum is set too low — callers must size `min_passes` to required checks.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| LLM-as-judge verifier builtin | Brittle on numeric/code outputs; conflicts with evaluation-first posture |
| Require all verifiers to pass | Too strict when some checks are optional per candidate type |
| Add `jsonschema` dependency | Keeps MVP zero-dependency; subset covers common metadata gates |
