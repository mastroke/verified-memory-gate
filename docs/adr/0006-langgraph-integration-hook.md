# ADR 0006: LangGraph integration hook

## Status

Accepted — 2026-06-25

## Context

ADR 0005 positioned `GateMemAgentStub` as the agent-facing boundary for
memory writes and reads. LangGraph-style orchestrators still need a concrete
wiring pattern: a post-run node that proposes lessons through EDV, and a guard
that stops agents from calling direct `save_memory`-style tools that bypass
`MemoryGate.commit`.

Rejection and pending outcomes must land in agent state so human reviewers see
why a lesson was blocked without digging into gate internals.

## Decision

1. Ship `langgraph_hook` with **no LangGraph package dependency** — nodes are
   plain callables returning state patches compatible with LangGraph reducers.
2. **`propose_memory` / `make_propose_memory_node`** — post-run middleware reads
   `executor_traces` and `distill_context` from state, runs
   `MemoryGate.commit`, and writes `memory_commit_result`,
   `memory_rejection_reasons`, and `memory_review_required`.
3. **`MemoryToolGuard` / `guard_tool_call`** — block a fixed set of direct
   memory tool names; append blocked attempts to `blocked_memory_tool_calls`
   and surface the bypass message for review.
4. **Dict coercion** — traces and context may be dataclasses or JSON-friendly
   dicts so checkpoint serializers can round-trip agent state.

## Consequences

**Positive**

- Orchestrators get a single integration seam without pulling LangGraph into
  core dependencies.
- Human review loops read explicit rejection tuples from agent state.
- Tool guard closes the bypass path ADR 0001 identified at the write boundary.

**Negative**

- Blocked tool list is static; custom tool names need guard configuration.
- No built-in LangGraph `StateGraph` wiring — callers compose nodes themselves.
- Post-run proposal assumes traces are already in state; capture hooks are
  orchestrator-specific.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Hard dependency on `langgraph` | Conflicts with zero-dep core; most teams pin versions separately |
| Monkey-patch LangChain memory tools | Fragile across framework versions; explicit guard is inspectable |
| Inline commit in agent system prompt only | No enforcement; agents still call write tools when available |
