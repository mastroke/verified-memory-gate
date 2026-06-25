# ADR 0005: GateMem regression harness for CI policy gating

## Status

Accepted — 2026-06-25

## Context

ADR 0004 added read ACL, leak-target metadata, and tombstone propagation so
retrieval aligns with GateMem access-control and active-forgetting probes.
Without an automated runner, policy regressions still slip through when store or
governance code changes — the same class of failure GateMem documents on
production memory agents.

The full GateMem benchmark ships 91 long-form episodes and LLM judges. This
repo needs a **subset harness** that runs in unit-test time, scores the
memory-gate retrieval path deterministically, and emits MGS components for CI.

## Decision

1. Ship `gatemem_episodes.SUBSET_EPISODES` — four fixture episodes spanning
   office, medical, household, and education domains with utility, access, and
   forgetting checkpoints.
2. Introduce `GateMemAgentStub` — a minimal shared-memory agent whose writes go
   through `MemoryGate.commit` and reads through `MemoryGate.retrieve`.
3. Score probes with structured rules (substring match, leak-target absence,
   tombstone + embedding-index non-recovery) rather than LLM judges.
4. Aggregate per-category rates into GateMem-aligned metrics:
   - **U** — utility pass rate on authorized probes
   - **A** — access-control violation rate
   - **F** — active-forgetting failure rate
   - **MGS** — `U × (1 − A) × (1 − F)`
5. Expose `run_harness()` and `GateMemThresholds` so CI and callers can gate
   deploys on perfect MGS for the fixture subset.

## Consequences

**Positive**

- Policy changes to ACL or tombstones are regression-tested like unit tests.
- MGS report dict is leaderboard-compatible at the metric level (U, A, F, MGS).
- Stub boundary is the integration seam for LangGraph hook work in r6.

**Negative**

- Fixture episodes are not the official GateMem dataset; scores are indicative,
  not leaderboard-submittable.
- Utility probes use substring match, not judge-based factual completeness.
- No latency or token efficiency metrics from the full benchmark.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Vendor full GateMem JSON + LLM judges | Heavy deps, flaky CI, out of MVP scope |
| pytest-only assertions without MGS | Loses GateMem-aligned reporting for drift alerts |
| Score raw store instead of gate retrieve | Skips the agent-facing retrieval boundary GateMem probes |
