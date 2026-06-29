#!/usr/bin/env python3
"""End-to-end demo: ExecutorTrace → EDV pipeline → MemoryGate.commit.

Runs one commit that passes verification and one that is rejected at the
verify stage. Install the package first::

    pip install -e .

Then::

    python examples/edv_commit_demo.py
"""

from __future__ import annotations

import sys
from typing import Sequence

from verified_memory_gate import (
    CommitResult,
    DistillContext,
    ExecutorTrace,
    MemoryGate,
    MemoryScope,
    QuorumConfig,
    RetrievalFilter,
    STAGE_DISTILL,
    STAGE_EXECUTE,
    VerifierRegistry,
)
from verified_memory_gate.builtin_verifiers import (
    JsonSchemaVerifier,
    NumericToleranceVerifier,
    PytestExitCodeVerifier,
)


def _build_gate() -> MemoryGate:
    registry = VerifierRegistry(
        verifiers=(
            PytestExitCodeVerifier(),
            NumericToleranceVerifier(anchor="sharpe", expected=0.62, tolerance=0.05),
            JsonSchemaVerifier(
                schema={
                    "type": "object",
                    "required": ("strategy_id",),
                    "properties": {"strategy_id": {"type": "string"}},
                }
            ),
        ),
        quorum=QuorumConfig(min_passes=2),
    )
    return MemoryGate.with_verifiers(registry)


def _print_stage(gate: MemoryGate, stage: str) -> None:
    output = gate.stage_output(stage)
    print(f"  {stage}: {output.content.replace(chr(10), '; ')}")


def _print_commit(label: str, result: CommitResult, gate: MemoryGate) -> None:
    print(f"\n--- {label} ---")
    _print_stage(gate, STAGE_EXECUTE)
    _print_stage(gate, STAGE_DISTILL)
    if result.committed:
        print("  verify: quorum passed (pytest, sharpe tolerance, schema)")
    else:
        print("  verify: quorum failed")
    print(f"  commit: {result.status.value.upper()}", end="")
    if result.memory_id:
        print(f"  memory_id={result.memory_id}")
    else:
        print()
    if result.reasons:
        for reason in result.reasons:
            print(f"    reason: {reason}")


def _committed_case(gate: MemoryGate) -> CommitResult:
    lesson = "Require Sharpe > 0.5 before promoting a strategy to paper trading."
    traces: Sequence[ExecutorTrace] = (
        ExecutorTrace(
            executor_id="research-agent",
            content=lesson,
            trace_id="backtest-run-17",
            evidence=("metric:sharpe=0.62", "pytest:passed"),
            metadata={"strategy_id": "mom-v2"},
        ),
        ExecutorTrace(
            executor_id="audit-agent",
            content="Cross-check confirms sharpe=0.62 on holdout.",
            trace_id="backtest-run-17",
        ),
    )
    context = DistillContext(
        principal="quant-research",
        scope=MemoryScope.TEAM,
        relationship="derived_from",
        classification="episodic",
        trace_id="backtest-run-17",
        metadata={"strategy_id": "mom-v2"},
    )
    result = gate.commit(traces, context)
    _print_commit("Committed — verify quorum passes", result, gate)
    return result


def _rejected_case(gate: MemoryGate) -> CommitResult:
    lesson = "Promote strategy after in-sample peak without holdout check."
    traces: Sequence[ExecutorTrace] = (
        ExecutorTrace(
            executor_id="research-agent",
            content=lesson,
            trace_id="backtest-run-18",
            evidence=("metric:sharpe=0.38", "pytest:failed"),
            metadata={"strategy_id": "mom-v2"},
        ),
        ExecutorTrace(
            executor_id="audit-agent",
            content="Holdout sharpe=0.38; below promotion threshold.",
            trace_id="backtest-run-18",
        ),
    )
    context = DistillContext(
        principal="quant-research",
        scope=MemoryScope.TEAM,
        relationship="derived_from",
        classification="episodic",
        trace_id="backtest-run-18",
        metadata={"strategy_id": "mom-v2"},
    )
    result = gate.commit(traces, context)
    _print_commit("Rejected — verify quorum fails", result, gate)
    return result


def main() -> int:
    print("Verified Memory Gate — EDV commit demo")
    print("ExecutorTrace → Execute → Distill → Verify → MemoryGate.commit\n")

    gate = _build_gate()
    committed = _committed_case(gate)
    rejected = _rejected_case(gate)

    stored = gate.retrieve(
        RetrievalFilter(requester="quant-research", principal="quant-research", scope="team")
    )
    print(f"\nStore after demo: {len(stored)} committed memory row(s)")
    if stored:
        print(f"  lesson: {stored[0].lesson[:72]}...")

    if not committed.committed or not rejected.rejected:
        print("\nDemo failed: expected one commit and one rejection.", file=sys.stderr)
        return 1

    print("\nDone — one lesson persisted, one blocked at verify.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
