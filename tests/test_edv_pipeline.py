"""Tests for the EDV three-stage pipeline (roadmap r3)."""

from __future__ import annotations

from verified_memory_gate import (
    CommitStatus,
    DistillContext,
    EDVCoordinator,
    EDVPipeline,
    EDVStageResult,
    ExecuteStage,
    ExecutorTrace,
    MemoryGate,
    MemoryScope,
    QuorumConfig,
    RuleBasedDistiller,
    STAGE_DISTILL,
    STAGE_EXECUTE,
    STAGE_VERIFY,
    VerifierRegistry,
    WindowBinding,
)
from verified_memory_gate.builtin_verifiers import PytestExitCodeVerifier
from verified_memory_gate.store import InMemoryStore
from tests.conftest import distill_context, dual_traces


def test_execute_rejects_single_trace_by_default() -> None:
    pipeline = EDVPipeline()
    traces = (ExecutorTrace(executor_id="solo", content="one trace only"),)
    context = distill_context()

    result = pipeline.run(traces, context)

    assert not result.ok
    assert any("at least 2 traces" in r for r in result.reasons)
    assert len(result.stages) == 1
    assert result.stages[0].stage == STAGE_EXECUTE


def test_execute_rejects_empty_trace_content() -> None:
    pipeline = EDVPipeline(execute=ExecuteStage(min_traces=1))
    traces = (ExecutorTrace(executor_id="agent", content="   "),)
    context = distill_context()

    result = pipeline.run(traces, context)

    assert not result.ok
    assert any("content must be non-empty" in r for r in result.reasons)


def test_distill_merges_evidence_from_all_traces() -> None:
    pipeline = EDVPipeline(execute=ExecuteStage(min_traces=1))
    traces = (
        ExecutorTrace(
            executor_id="research",
            content="Sharpe exceeded threshold on holdout.",
            evidence=("pytest:passed",),
            trace_id="run-9",
        ),
        ExecutorTrace(
            executor_id="audit",
            content="Confirmed metric stability.",
            evidence=("metric:sharpe=0.61",),
        ),
    )
    context = distill_context(trace_id="run-9")

    result = pipeline.run(traces, context)

    assert result.ok
    assert result.candidate is not None
    assert result.candidate.lesson == "Sharpe exceeded threshold on holdout."
    assert "pytest:passed" in result.candidate.evidence
    assert "metric:sharpe=0.61" in result.candidate.evidence
    assert "executor:research" in result.candidate.evidence


def test_rule_based_distiller_selects_executor_by_id() -> None:
    pipeline = EDVPipeline(
        execute=ExecuteStage(min_traces=1),
        distiller=RuleBasedDistiller(lesson_executor_id="research"),
    )
    traces = (
        ExecutorTrace(executor_id="audit", content="audit view"),
        ExecutorTrace(executor_id="research", content="research lesson"),
    )
    context = distill_context()

    result = pipeline.run(traces, context)

    assert result.ok
    assert result.candidate is not None
    assert result.candidate.lesson == "research lesson"


def test_verify_stage_rejects_on_quorum_failure() -> None:
    registry = VerifierRegistry(
        verifiers=(PytestExitCodeVerifier(),),
        quorum=QuorumConfig(min_passes=1),
    )
    pipeline = EDVPipeline.with_verifiers(registry)
    traces = dual_traces(
        "Lesson with failing pytest evidence.",
        evidence=("pytest:failed",),
    )
    context = distill_context()

    result = pipeline.run(traces, context)

    assert not result.ok
    assert result.stages[-1].stage == STAGE_VERIFY
    assert any("pytest" in r for r in result.reasons)


def test_pipeline_stages_recorded_in_order() -> None:
    pipeline = EDVPipeline(execute=ExecuteStage(min_traces=1))
    traces = dual_traces("Ordered stage recording.")
    context = distill_context()

    result = pipeline.run(traces, context)

    assert result.ok
    assert [stage.stage for stage in result.stages] == [
        STAGE_EXECUTE,
        STAGE_DISTILL,
        STAGE_VERIFY,
    ]


def test_gate_commit_rejects_when_execute_fails() -> None:
    gate = MemoryGate(store=InMemoryStore())
    traces = (ExecutorTrace(executor_id="solo", content="only one"),)
    context = distill_context()

    result = gate.commit(traces, context)

    assert result.status is CommitStatus.REJECTED
    assert gate.store.count() == 0


def test_coordinator_routes_stage_output_to_windows() -> None:
    rendered: dict[str, str] = {}

    def capture(window_id: str, output) -> None:
        rendered[window_id] = output.content

    pipeline = EDVPipeline(execute=ExecuteStage(min_traces=1))
    coordinator = EDVCoordinator(
        pipeline=pipeline,
        bindings=EDVCoordinator.default_bindings(),
        store=InMemoryStore(),
        on_render=capture,
    )
    traces = dual_traces("Window routing test.")
    context = distill_context()

    result = coordinator.commit(traces, context)

    assert result.committed
    assert "display-execute" in rendered
    assert "display-distill" in rendered
    assert "display-verify" in rendered
    assert coordinator.stage_output(STAGE_DISTILL).content == "Window routing test."


def test_custom_distiller_protocol() -> None:
    from verified_memory_gate import CandidateExperience

    class FixedDistiller:
        name = "fixed"

        def distill(self, bundle, context: DistillContext) -> EDVStageResult:
            return EDVStageResult(
                ok=True,
                stage=STAGE_DISTILL,
                candidate=CandidateExperience(
                    lesson="fixed lesson",
                    principal=context.principal,
                    scope=context.scope,
                ),
            )

    pipeline = EDVPipeline(
        execute=ExecuteStage(min_traces=1),
        distiller=FixedDistiller(),
    )
    traces = dual_traces("ignored by fixed distiller")
    context = distill_context()

    result = pipeline.run(traces, context)

    assert result.ok
    assert result.candidate is not None
    assert result.candidate.lesson == "fixed lesson"


def test_gate_stage_output_after_commit() -> None:
    gate = MemoryGate(
        store=InMemoryStore(),
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
        bindings=(
            WindowBinding(window_id="w-distill", stage=STAGE_DISTILL),
        ),
    )
    traces = dual_traces("Stage output snapshot.")
    context = distill_context()

    gate.commit(traces, context)

    assert gate.stage_output(STAGE_DISTILL).content == "Stage output snapshot."
