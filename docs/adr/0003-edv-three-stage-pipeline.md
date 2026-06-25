# ADR 0003: EDV three-stage pipeline as the only commit path

## Status

Accepted — 2026-06-25

## Context

ADR 0002 wired verifier quorum directly inside `MemoryGate.commit()` when a
`CandidateExperience` was supplied. That bypassed the Execute and Distill stages
described in EDV research: heterogeneous executor traces must be ingested and
distilled into a structured lesson before verification runs. Without this
separation, orchestrators could still push self-consistent but unverified
lessons straight into storage.

Multi-monitor agent setups also need stage output routed to distinct windows
(execute traces, distilled lesson, verify quorum) while a coordinator holds
shared pipeline state until verify passes.

## Decision

1. Introduce `ExecutorTrace`, `DistillContext`, and `EDVPipeline` with three
   explicit stages:
   - **Execute** — ingest and validate multi-trace executor output
     (`ExecuteStage`, default `min_traces=2`).
   - **Distill** — extract a `CandidateExperience` via a pluggable `Distiller`
     protocol; ship `RuleBasedDistiller` (primary trace content + merged evidence).
   - **Verify** — run `VerifierRegistry` quorum on the distilled candidate.
2. `MemoryGate.commit(traces, context)` is the **only** write path; direct
   candidate commits are removed. Governance validation still runs on the
   distilled candidate before persistence or manual-review enqueue.
3. Add `EDVCoordinator` with `WindowBinding` so each EDV stage can render to a
   bound display window; `MemoryGate` exposes the same bindings via optional
   `on_render` callbacks and `stage_output()`.
4. `MemoryGate.with_verifiers()` builds a pipeline whose verify stage uses the
   supplied registry.

## Consequences

**Positive**

- Execute → Distill → Verify is enforced at the API boundary, matching EDV
  verify-before-insert semantics.
- Distillers are pluggable (rule-based now; LLM distiller via custom `Distiller`
  implementations).
- Window bindings prepare for the local daemon milestone (r7) without coupling
  persistence to display hardware.

**Negative**

- Callers must supply at least two executor traces by default; single-trace flows
  need `ExecuteStage(min_traces=1)` or a second audit trace.
- Distillation quality depends on distiller choice; rule-based defaults are
  intentionally minimal.
- `approve()` still promotes pre-verified pending rows; re-running EDV on approve
  is deferred to avoid double-verify latency.

## Alternatives considered

| Alternative | Why rejected |
| --- | --- |
| Keep direct `CandidateExperience` commit alongside EDV | Leaves self-confirmation bypass open |
| LLM distiller builtin | Adds dependency and non-determinism; protocol + rule-based default suffices for r3 |
| Async multi-process coordinator | Scope belongs to r7 daemon; in-process bindings cover r3 |
