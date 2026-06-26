"""Write interceptor that validates governance tags before persistence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable
from uuid import uuid4

from verified_memory_gate.audit_log import AppendOnlyAuditLog
from verified_memory_gate.coordinator import RenderCallback
from verified_memory_gate.edv import (
    STAGE_VERIFY,
    DistillContext,
    EDVPipeline,
    EDVPipelineResult,
    ExecuteStage,
    ExecutorTrace,
    RuleBasedDistiller,
    StageOutput,
    WindowBinding,
)
from verified_memory_gate.verifiers import ConsensusResult
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
    audit_log: AppendOnlyAuditLog | None = None
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
            result = CommitResult(
                status=CommitStatus.REJECTED,
                reasons=pipeline_result.reasons,
            )
            self._audit_write(context, pipeline_result, result)
            return result

        candidate = pipeline_result.candidate
        if candidate is None:
            result = CommitResult(
                status=CommitStatus.REJECTED,
                reasons=("pipeline succeeded without candidate",),
            )
            self._audit_write(context, pipeline_result, result)
            return result

        errors = self.validate(candidate)
        if errors:
            result = CommitResult(status=CommitStatus.REJECTED, reasons=errors)
            self._audit_write(context, pipeline_result, result)
            return result

        if self.mode is GateMode.MANUAL_REVIEW:
            pending_id = str(uuid4())
            self._pending[pending_id] = PendingCandidate(
                pending_id=pending_id,
                candidate=candidate,
            )
            result = CommitResult(
                status=CommitStatus.PENDING,
                pending_id=pending_id,
                reasons=("awaiting manual review",),
            )
            self._audit_write(context, pipeline_result, result)
            return result

        entry = MemoryEntry.from_candidate(candidate)
        self.store.insert(entry)
        result = CommitResult(status=CommitStatus.COMMITTED, memory_id=entry.memory_id)
        self._audit_write(context, pipeline_result, result)
        return result

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
        result = CommitResult(status=CommitStatus.COMMITTED, memory_id=entry.memory_id)
        self._audit_write_for_candidate(
            pending.candidate.principal,
            pending.candidate,
            result,
        )
        return result

    def forget(self, memory_id: str, principal: str) -> bool:
        """Tombstone a memory and propagate deletion to the embedding index."""
        success = self.store.tombstone(memory_id, principal)
        if self.audit_log is not None:
            reasons: tuple[str, ...] = ()
            if not success:
                reasons = ("tombstone rejected or unknown memory_id",)
            self.audit_log.record_deletion(
                actor=principal,
                memory_id=memory_id,
                success=success,
                reasons=reasons,
            )
        return success

    def bind_embedding(self, memory_id: str, vector_id: str) -> bool:
        """Register an embedding-index mapping for a committed memory row."""
        return self.store.bind_embedding(memory_id, vector_id)

    def embedding_vector_id(self, memory_id: str) -> str | None:
        """Return the embedding id for *memory_id*, or None when tombstoned."""
        return self.store.embedding_vector_id(memory_id)

    def retrieve(self, filters: RetrievalFilter | None = None) -> list[MemoryEntry]:
        """List committed memories with principal-scoped ACL and tag filters."""
        return self.store.list(filters)

    def _verify_consensus(
        self, pipeline_result: EDVPipelineResult
    ) -> ConsensusResult | None:
        for stage in pipeline_result.stages:
            if stage.stage == STAGE_VERIFY:
                return stage.consensus
        return None

    def _audit_write(
        self,
        context: DistillContext,
        pipeline_result: EDVPipelineResult,
        result: CommitResult,
    ) -> None:
        if self.audit_log is None:
            return
        candidate = pipeline_result.candidate
        if candidate is None and self._latest is not None:
            candidate = self._latest.candidate
        self.audit_log.record_write(
            actor=context.principal,
            result=result,
            candidate=candidate,
            consensus=self._verify_consensus(pipeline_result),
        )

    def _audit_write_for_candidate(
        self,
        actor: str,
        candidate: CandidateExperience,
        result: CommitResult,
    ) -> None:
        if self.audit_log is None:
            return
        self.audit_log.record_write(
            actor=actor,
            result=result,
            candidate=candidate,
            consensus=None,
        )
