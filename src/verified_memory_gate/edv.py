"""Execute → Distill → Verify pipeline — the only path to memory commit."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from verified_memory_gate.models import CandidateExperience, MemoryScope
from verified_memory_gate.verifiers import ConsensusResult, VerifierRegistry


@dataclass(frozen=True, slots=True)
class ExecutorTrace:
    """Raw output from one heterogeneous agent executor run."""

    executor_id: str
    content: str
    trace_id: str | None = None
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DistillContext:
    """Governance tags applied when distilling traces into a candidate lesson."""

    principal: str
    scope: MemoryScope | str
    relationship: str = "derived_from"
    classification: str = "episodic"
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExecuteBundle:
    """Normalized multi-trace bundle after the execute stage."""

    traces: tuple[ExecutorTrace, ...]


@dataclass(frozen=True, slots=True)
class StageOutput:
    """Rendered output for one EDV stage window."""

    stage: str
    content: str
    candidate: CandidateExperience | None = None


@dataclass(frozen=True, slots=True)
class EDVStageResult:
    """Outcome from one pipeline stage."""

    ok: bool
    stage: str
    candidate: CandidateExperience | None = None
    reasons: tuple[str, ...] = ()
    consensus: ConsensusResult | None = None

    @property
    def output(self) -> StageOutput:
        if self.candidate is not None:
            body = self.candidate.lesson
        elif self.reasons:
            body = "\n".join(self.reasons)
        else:
            body = f"{self.stage}: ok" if self.ok else f"{self.stage}: failed"
        return StageOutput(stage=self.stage, content=body, candidate=self.candidate)


STAGE_EXECUTE = "execute"
STAGE_DISTILL = "distill"
STAGE_VERIFY = "verify"


@dataclass(frozen=True, slots=True)
class WindowBinding:
    """Maps a physical display window to one EDV stage."""

    window_id: str
    stage: str


@dataclass
class ExecuteStage:
    """Ingest and validate multi-trace executor output."""

    min_traces: int = 2

    def ingest(self, traces: tuple[ExecutorTrace, ...]) -> EDVStageResult:
        if len(traces) < self.min_traces:
            return EDVStageResult(
                ok=False,
                stage=STAGE_EXECUTE,
                reasons=(
                    f"execute requires at least {self.min_traces} traces, "
                    f"got {len(traces)}",
                ),
            )

        errors: list[str] = []
        for index, trace in enumerate(traces):
            if not trace.executor_id or not trace.executor_id.strip():
                errors.append(f"trace[{index}] missing executor_id")
            if not trace.content or not trace.content.strip():
                errors.append(f"trace[{index}] content must be non-empty")

        if errors:
            return EDVStageResult(
                ok=False,
                stage=STAGE_EXECUTE,
                reasons=tuple(errors),
            )

        return EDVStageResult(
            ok=True,
            stage=STAGE_EXECUTE,
            candidate=None,
        )


@runtime_checkable
class Distiller(Protocol):
    """Extract a structured candidate lesson from an execute bundle."""

    name: str

    def distill(
        self, bundle: ExecuteBundle, context: DistillContext
    ) -> EDVStageResult:
        """Return a distilled candidate or stage failure reasons."""
        ...


@dataclass(frozen=True, slots=True)
class RuleBasedDistiller:
    """Rule-based distiller: pick lesson trace and merge evidence."""

    name: str = "rule_based"
    lesson_executor_id: str | None = None

    def distill(
        self, bundle: ExecuteBundle, context: DistillContext
    ) -> EDVStageResult:
        lesson_trace = self._select_lesson_trace(bundle.traces)
        if lesson_trace is None:
            return EDVStageResult(
                ok=False,
                stage=STAGE_DISTILL,
                reasons=("no trace available for lesson extraction",),
            )

        evidence: list[str] = []
        metadata: dict[str, Any] = dict(context.metadata)
        trace_id = context.trace_id

        for trace in bundle.traces:
            evidence.extend(trace.evidence)
            evidence.append(f"executor:{trace.executor_id}")
            metadata.update(trace.metadata)
            if trace_id is None and trace.trace_id:
                trace_id = trace.trace_id

        candidate = CandidateExperience(
            lesson=lesson_trace.content.strip(),
            principal=context.principal,
            scope=context.scope,
            relationship=context.relationship,
            classification=context.classification,
            trace_id=trace_id,
            evidence=tuple(dict.fromkeys(evidence)),
            metadata=metadata,
        )
        return EDVStageResult(
            ok=True,
            stage=STAGE_DISTILL,
            candidate=candidate,
        )

    def _select_lesson_trace(
        self, traces: tuple[ExecutorTrace, ...]
    ) -> ExecutorTrace | None:
        if not traces:
            return None
        if self.lesson_executor_id is not None:
            for trace in traces:
                if trace.executor_id == self.lesson_executor_id:
                    return trace
            return None
        return traces[0]


@dataclass(frozen=True, slots=True)
class VerifyStage:
    """Run verifier quorum against a distilled candidate."""

    verifiers: VerifierRegistry | None = None

    def verify(self, candidate: CandidateExperience) -> EDVStageResult:
        if self.verifiers is None:
            return EDVStageResult(
                ok=True,
                stage=STAGE_VERIFY,
                candidate=candidate,
            )

        consensus = self.verifiers.evaluate(candidate)
        if consensus.passed:
            return EDVStageResult(
                ok=True,
                stage=STAGE_VERIFY,
                candidate=candidate,
                consensus=consensus,
            )

        return EDVStageResult(
            ok=False,
            stage=STAGE_VERIFY,
            candidate=candidate,
            reasons=consensus.reasons,
            consensus=consensus,
        )


@dataclass(frozen=True, slots=True)
class EDVPipelineResult:
    """Aggregated outcome after all EDV stages."""

    ok: bool
    candidate: CandidateExperience | None = None
    reasons: tuple[str, ...] = ()
    stages: tuple[EDVStageResult, ...] = ()

    def output_for(self, stage: str) -> StageOutput:
        for result in self.stages:
            if result.stage == stage:
                return result.output
        return StageOutput(stage=stage, content=f"{stage}: not reached")


@dataclass
class EDVPipeline:
    """Execute → Distill → Verify — mandatory pre-commit path."""

    execute: ExecuteStage = field(default_factory=ExecuteStage)
    distiller: Distiller = field(default_factory=RuleBasedDistiller)
    verify: VerifyStage = field(default_factory=VerifyStage)

    @classmethod
    def with_verifiers(cls, verifiers: VerifierRegistry | None) -> EDVPipeline:
        return cls(verify=VerifyStage(verifiers=verifiers))

    def run(
        self,
        traces: tuple[ExecutorTrace, ...],
        context: DistillContext,
    ) -> EDVPipelineResult:
        execute_result = self.execute.ingest(traces)
        if not execute_result.ok:
            return EDVPipelineResult(
                ok=False,
                reasons=execute_result.reasons,
                stages=(execute_result,),
            )

        bundle = ExecuteBundle(traces=traces)
        distill_result = self.distiller.distill(bundle, context)
        if not distill_result.ok or distill_result.candidate is None:
            return EDVPipelineResult(
                ok=False,
                reasons=distill_result.reasons,
                stages=(execute_result, distill_result),
            )

        verify_result = self.verify.verify(distill_result.candidate)
        stages = (execute_result, distill_result, verify_result)
        if not verify_result.ok:
            return EDVPipelineResult(
                ok=False,
                candidate=distill_result.candidate,
                reasons=verify_result.reasons,
                stages=stages,
            )

        return EDVPipelineResult(
            ok=True,
            candidate=distill_result.candidate,
            stages=stages,
        )
