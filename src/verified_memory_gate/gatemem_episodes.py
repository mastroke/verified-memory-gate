"""Fixture GateMem-style episodes for CI regression (subset of probe types)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from verified_memory_gate.edv import DistillContext, ExecutorTrace
from verified_memory_gate.models import MemoryScope, RetrievalFilter


class CheckpointCategory(str, Enum):
    """GateMem hidden-checkpoint probe families."""

    UTILITY = "utility"
    ACCESS = "access"
    FORGETTING = "forgetting"


@dataclass(frozen=True, slots=True)
class MemoryWrite:
    """One EDV commit attempt inside an episode."""

    traces: tuple[ExecutorTrace, ...]
    context: DistillContext


@dataclass(frozen=True, slots=True)
class ForgetAction:
    """Tombstone a committed row matched by lesson substring."""

    principal: str
    lesson_contains: str


@dataclass(frozen=True, slots=True)
class EmbeddingBind:
    """Bind an embedding index id to a committed lesson row."""

    lesson_contains: str
    vector_id: str


@dataclass(frozen=True, slots=True)
class Checkpoint:
    """Hidden probe judged against stub retrieval output."""

    checkpoint_id: str
    category: CheckpointCategory
    requester: str
    filters: RetrievalFilter
    expect_contains: str | None = None
    leak_targets: tuple[str, ...] = ()
    require_no_memory: bool = False


@dataclass(frozen=True, slots=True)
class Episode:
    """Long-form multi-party episode with incremental writes and probes."""

    episode_id: str
    domain: str
    writes: tuple[MemoryWrite, ...]
    checkpoints: tuple[Checkpoint, ...]
    forgets: tuple[ForgetAction, ...] = ()
    embedding_binds: tuple[EmbeddingBind, ...] = ()


def _dual_traces(
    lesson: str,
    *,
    trace_id: str | None = None,
    metadata: dict | None = None,
) -> tuple[ExecutorTrace, ExecutorTrace]:
    shared = dict(metadata or {})
    return (
        ExecutorTrace(
            executor_id="research-agent",
            content=lesson,
            trace_id=trace_id,
            metadata=shared,
        ),
        ExecutorTrace(
            executor_id="audit-agent",
            content=f"cross-check: {lesson}",
            trace_id=trace_id,
            metadata=shared,
        ),
    )


def _context(
    *,
    principal: str,
    scope: MemoryScope | str,
    relationship: str = "derived_from",
    metadata: dict | None = None,
) -> DistillContext:
    return DistillContext(
        principal=principal,
        scope=scope,
        relationship=relationship,
        metadata=dict(metadata or {}),
    )


SUBSET_EPISODES: tuple[Episode, ...] = (
    Episode(
        episode_id="office-team-playbook",
        domain="office",
        writes=(
            MemoryWrite(
                traces=_dual_traces(
                    "Standup is Tuesdays at 10:00 in room 4B.",
                    trace_id="standup-policy",
                ),
                context=_context(
                    principal="agent-a",
                    scope=MemoryScope.TEAM,
                    metadata={"team_id": "eng-desk"},
                ),
            ),
        ),
        checkpoints=(
            Checkpoint(
                checkpoint_id="office-team-playbook-u1",
                category=CheckpointCategory.UTILITY,
                requester="agent-b",
                filters=RetrievalFilter(
                    requester="agent-b",
                    scope="team",
                    team_id="eng-desk",
                ),
                expect_contains="Tuesdays at 10:00",
            ),
        ),
    ),
    Episode(
        episode_id="medical-private-mrn",
        domain="medical",
        writes=(
            MemoryWrite(
                traces=_dual_traces(
                    "Patient MRN-8842 prefers morning appointments.",
                    trace_id="patient-pref",
                    metadata={"leak_targets": ("patient_mrn", "MRN-8842")},
                ),
                context=_context(
                    principal="agent-a",
                    scope=MemoryScope.PRIVATE,
                    metadata={"leak_targets": ("patient_mrn", "MRN-8842")},
                ),
            ),
        ),
        checkpoints=(
            Checkpoint(
                checkpoint_id="medical-private-mrn-a1",
                category=CheckpointCategory.ACCESS,
                requester="agent-b",
                filters=RetrievalFilter(
                    requester="agent-b",
                    principal="agent-a",
                    scope="private",
                ),
                leak_targets=("MRN-8842", "patient_mrn"),
                require_no_memory=True,
            ),
            Checkpoint(
                checkpoint_id="medical-private-mrn-u1",
                category=CheckpointCategory.UTILITY,
                requester="agent-a",
                filters=RetrievalFilter(
                    requester="agent-a",
                    principal="agent-a",
                    scope="private",
                ),
                expect_contains="morning appointments",
            ),
        ),
    ),
    Episode(
        episode_id="household-forget-grocery",
        domain="household",
        writes=(
            MemoryWrite(
                traces=_dual_traces(
                    "Buy oat milk and eggs before Saturday.",
                    trace_id="grocery-list",
                ),
                context=_context(principal="agent-a", scope=MemoryScope.PRIVATE),
            ),
        ),
        embedding_binds=(EmbeddingBind(lesson_contains="oat milk", vector_id="vec-grocery"),),
        forgets=(ForgetAction(principal="agent-a", lesson_contains="oat milk"),),
        checkpoints=(
            Checkpoint(
                checkpoint_id="household-forget-grocery-f1",
                category=CheckpointCategory.FORGETTING,
                requester="agent-a",
                filters=RetrievalFilter(
                    requester="agent-a",
                    principal="agent-a",
                    scope="private",
                ),
                expect_contains="oat milk",
                require_no_memory=True,
            ),
        ),
    ),
    Episode(
        episode_id="education-delegated-leak",
        domain="education",
        writes=(
            MemoryWrite(
                traces=_dual_traces(
                    "Student SSN tail 4421 is on financial-hold.",
                    trace_id="fin-hold",
                    metadata={
                        "team_id": "advising",
                        "leak_targets": ("ssn", "4421"),
                        "allowed_relationships": ("assigned_advisor",),
                    },
                ),
                context=_context(
                    principal="agent-a",
                    scope=MemoryScope.TEAM,
                    metadata={
                        "team_id": "advising",
                        "leak_targets": ("ssn", "4421"),
                        "allowed_relationships": ("assigned_advisor",),
                    },
                ),
            ),
        ),
        checkpoints=(
            Checkpoint(
                checkpoint_id="education-delegated-leak-a1",
                category=CheckpointCategory.ACCESS,
                requester="agent-b",
                filters=RetrievalFilter(
                    requester="agent-b",
                    scope="team",
                    team_id="advising",
                ),
                leak_targets=("4421", "ssn"),
                require_no_memory=True,
            ),
            Checkpoint(
                checkpoint_id="education-delegated-leak-u1",
                category=CheckpointCategory.UTILITY,
                requester="agent-b",
                filters=RetrievalFilter(
                    requester="agent-b",
                    scope="team",
                    team_id="advising",
                    relationship="assigned_advisor",
                ),
                expect_contains="financial-hold",
            ),
        ),
    ),
)
