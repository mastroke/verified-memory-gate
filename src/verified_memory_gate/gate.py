"""Write interceptor that validates governance tags before persistence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable
from uuid import uuid4

from verified_memory_gate.coordinator import RenderCallback
from verified_memory_gate.edv import (
    DistillContext,
    EDVPipeline,
    EDVPipelineResult,
    ExecuteStage,
    ExecutorTrace,
    RuleBasedDistiller,
    StageOutput,
    WindowBinding,
)
from verified_memory_gate.models import (
    CandidateExperience,
    CommitResult,
    CommitStatus,
    MemoryEntry,
    PendingCandidate,
    RetrievalFilter,
)
from verified_memory_gate.store import InMemoryStore
from verified_memory_gate.verifiers import VerifierRegistry

_VALID_CLASSIFICATIONS = frozenset({"episodic", "semantic", "procedural"})


class GateMode(str, Enum):
    """How the gate handles candidates that pass schema validation."""

    AUTO_COMMIT = "auto_commit"
    MANUAL_REVIEW = "manual_review"


@dataclass
class MemoryGate:
    """Intercept candidate memory writes and enforce governance before storage."""

    store: InMemoryStore | None = None
    mode: GateMode = GateMode.AUTO_COMMIT
    pipeline: EDVPipeline | None = None
    bindings: tuple[WindowBinding, ...] = ()
    on_render: RenderCallback | None = None
    _pending: dict[str, PendingCandidate] = field(default_factory=dict, repr=False)
    _latest: EDVPipelineResult | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.store is None:
            self.store = InMemoryStore()
        if self.pipeline is None:
            self.pipeline = EDVPipeline()

    @classmethod
    def with_verifiers(
        cls,
        verifiers: VerifierRegistry | None,
        *,
        store: InMemoryStore | None = None,
        mode: GateMode = GateMode.AUTO_COMMIT,
        execute: ExecuteStage | None = None,
        min_traces: int | None = None,
    ) -> MemoryGate:
        """Build a gate whose verify stage uses the given verifier registry."""
        execute_stage = execute or ExecuteStage(
            min_traces=min_traces if min_traces is not None else 2
        )
        pipeline = EDVPipeline(
            execute=execute_stage,
            distiller=RuleBasedDistiller(),
            verify=EDVPipeline.with_verifiers(verifiers).verify,
        )
        return cls(store=store, mode=mode, pipeline=pipeline)

    def validate(self, candidate: CandidateExperience) -> tuple[str, ...]:
        """Return validation error messages; empty tuple means valid."""
        errors: list[str] = []

        if not candidate.lesson or not candidate.lesson.strip():
            errors.append("lesson must be non-empty")

        if not candidate.principal or not candidate.principal.strip():
            errors.append("principal is required for governance tagging")

        scope = candidate.normalized_scope()
        if not scope:
            errors.append("scope is required for access isolation")

        if not candidate.relationship or not candidate.relationship.strip():
            errors.append("relationship tag is required")

        classification = candidate.classification.strip() if candidate.classification else ""
        if classification not in _VALID_CLASSIFICATIONS:
            errors.append(
                f"classification must be one of {sorted(_VALID_CLASSIFICATIONS)}"
            )

        return tuple(errors)

    def commit(
        self,
        traces: Sequence[ExecutorTrace],
        context: DistillContext,
    ) -> CommitResult:
        """Persist a memory only after Execute → Distill → Verify succeeds."""
        trace_tuple = tuple(traces)
        pipeline_result = self.pipeline.run(trace_tuple, context)
        self._latest = pipeline_result
        self._render_stage_outputs(pipeline_result)

        if not pipeline_result.ok:
            return CommitResult(
                status=CommitStatus.REJECTED,
                reasons=pipeline_result.reasons,
            )

        candidate = pipeline_result.candidate
        if candidate is None:
            return CommitResult(
                status=CommitStatus.REJECTED,
                reasons=("pipeline succeeded without candidate",),
            )

        errors = self.validate(candidate)
        if errors:
            return CommitResult(status=CommitStatus.REJECTED, reasons=errors)

        if self.mode is GateMode.MANUAL_REVIEW:
            pending_id = str(uuid4())
            self._pending[pending_id] = PendingCandidate(
                pending_id=pending_id,
                candidate=candidate,
            )
            return CommitResult(
                status=CommitStatus.PENDING,
                pending_id=pending_id,
                reasons=("awaiting manual review",),
            )

        entry = MemoryEntry.from_candidate(candidate)
        self.store.insert(entry)
        return CommitResult(status=CommitStatus.COMMITTED, memory_id=entry.memory_id)

    def stage_output(self, stage: str) -> StageOutput:
        """Return the latest rendered output for one EDV stage window."""
        if self._latest is None:
            return StageOutput(stage=stage, content=f"{stage}: idle")
        return self._latest.output_for(stage)

    def _render_stage_outputs(self, result: EDVPipelineResult) -> None:
        if self.on_render is None or not self.bindings:
            return
        for binding in self.bindings:
            self.on_render(binding.window_id, result.output_for(binding.stage))

    def list_pending(
        self, filters: RetrievalFilter | None = None
    ) -> list[PendingCandidate]:
        """Return inbox candidates awaiting manual approval."""
        items = list(self._pending.values())
        if filters is None:
            return items

        if filters.principal is not None:
            items = [p for p in items if p.candidate.principal == filters.principal]
        if filters.scope is not None:
            items = [
                p
                for p in items
                if p.candidate.normalized_scope() == filters.scope
            ]
        if filters.classification is not None:
            items = [
                p for p in items if p.candidate.classification == filters.classification
            ]
        return items

    def approve(self, pending_id: str) -> CommitResult:
        """Promote a pending candidate into committed storage."""
        pending = self._pending.pop(pending_id, None)
        if pending is None:
            return CommitResult(
                status=CommitStatus.REJECTED,
                reasons=(f"unknown pending_id: {pending_id}",),
            )

        entry = MemoryEntry.from_candidate(pending.candidate)
        self.store.insert(entry)
        return CommitResult(status=CommitStatus.COMMITTED, memory_id=entry.memory_id)

    def retrieve(self, filters: RetrievalFilter | None = None) -> list[MemoryEntry]:
        """List committed memories, optionally filtered by governance tags."""
        return self.store.list(filters)
