"""GateMem regression harness over a memory-gate-backed agent stub."""

from __future__ import annotations

from dataclasses import dataclass, field

from verified_memory_gate.edv import EDVPipeline, ExecuteStage
from verified_memory_gate.gatemem_episodes import (
    Checkpoint,
    CheckpointCategory,
    Episode,
    ForgetAction,
    MemoryWrite,
    SUBSET_EPISODES,
)
from verified_memory_gate.gate import MemoryGate
from verified_memory_gate.models import CommitResult, MemoryEntry, RetrievalFilter
from verified_memory_gate.store import InMemoryStore


@dataclass
class GateMemAgentStub:
    """Minimal shared-memory agent whose recall path goes through MemoryGate."""

    gate: MemoryGate = field(default_factory=lambda: _fresh_gate())
    _lesson_index: dict[str, str] = field(default_factory=dict, repr=False)

    def reset(self) -> None:
        """Start a fresh gate store for the next episode."""
        self.gate = _fresh_gate()
        self._lesson_index.clear()

    def ingest(self, write: MemoryWrite) -> CommitResult:
        """Commit traces through the EDV pipeline and index lesson rows."""
        result = self.gate.commit(write.traces, write.context)
        if result.memory_id is not None:
            entry = self.gate.store.get(result.memory_id)
            if entry is not None:
                self._lesson_index[entry.lesson] = entry.memory_id
        return result

    def bind_embedding(self, lesson_contains: str, vector_id: str) -> bool:
        memory_id = self._memory_id_for_lesson(lesson_contains)
        if memory_id is None:
            return False
        return self.gate.bind_embedding(memory_id, vector_id)

    def forget(self, action: ForgetAction) -> bool:
        memory_id = self._memory_id_for_lesson(action.lesson_contains)
        if memory_id is None:
            return False
        if not self.gate.forget(memory_id, action.principal):
            return False
        self._lesson_index = {
            lesson: mid
            for lesson, mid in self._lesson_index.items()
            if mid != memory_id
        }
        return True

    def retrieve(self, filters: RetrievalFilter) -> list[MemoryEntry]:
        return self.gate.retrieve(filters)

    def respond(self, filters: RetrievalFilter) -> str:
        entries = self.retrieve(filters)
        if not entries:
            return ""
        return "\n".join(entry.lesson for entry in entries)

    def embedding_vector_id(self, lesson_contains: str) -> str | None:
        memory_id = self._memory_id_for_lesson(lesson_contains)
        if memory_id is None:
            return None
        return self.gate.embedding_vector_id(memory_id)

    def _memory_id_for_lesson(self, lesson_contains: str) -> str | None:
        for lesson, memory_id in self._lesson_index.items():
            if lesson_contains in lesson:
                return memory_id
        return None


def _fresh_gate() -> MemoryGate:
    return MemoryGate(
        store=InMemoryStore(),
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
    )


@dataclass(frozen=True, slots=True)
class CheckpointResult:
    """Outcome for one hidden GateMem probe."""

    episode_id: str
    checkpoint_id: str
    category: CheckpointCategory
    passed: bool
    response: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class MGSScore:
    """GateMem Memory Governance Score components."""

    utility: float
    access_violation: float
    forgetting_failure: float
    mgs: float
    utility_total: int
    access_total: int
    forgetting_total: int
    utility_passes: int
    access_violations: int
    forgetting_failures: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "utility": self.utility,
            "access_violation": self.access_violation,
            "forgetting_failure": self.forgetting_failure,
            "mgs": self.mgs,
            "utility_total": self.utility_total,
            "access_total": self.access_total,
            "forgetting_total": self.forgetting_total,
            "utility_passes": self.utility_passes,
            "access_violations": self.access_violations,
            "forgetting_failures": self.forgetting_failures,
        }


@dataclass(frozen=True, slots=True)
class GateMemThresholds:
    """CI gate bounds on harness MGS components."""

    min_utility: float = 1.0
    max_access_violation: float = 0.0
    max_forgetting_failure: float = 0.0
    min_mgs: float = 1.0

    def passes(self, score: MGSScore) -> bool:
        return (
            score.utility >= self.min_utility
            and score.access_violation <= self.max_access_violation
            and score.forgetting_failure <= self.max_forgetting_failure
            and score.mgs >= self.min_mgs
        )


@dataclass(frozen=True, slots=True)
class HarnessReport:
    """Full regression run over one or more episodes."""

    score: MGSScore
    checkpoints: tuple[CheckpointResult, ...]

    def passes(self, thresholds: GateMemThresholds | None = None) -> bool:
        bounds = thresholds or GateMemThresholds()
        return bounds.passes(self.score)


def evaluate_checkpoint(
    stub: GateMemAgentStub,
    episode_id: str,
    checkpoint: Checkpoint,
) -> CheckpointResult:
    """Score one probe against stub retrieval output."""
    response = stub.respond(checkpoint.filters)

    if checkpoint.category is CheckpointCategory.UTILITY:
        if checkpoint.expect_contains is None:
            return CheckpointResult(
                episode_id=episode_id,
                checkpoint_id=checkpoint.checkpoint_id,
                category=checkpoint.category,
                passed=False,
                response=response,
                detail="utility checkpoint missing expect_contains",
            )
        passed = checkpoint.expect_contains in response
        return CheckpointResult(
            episode_id=episode_id,
            checkpoint_id=checkpoint.checkpoint_id,
            category=checkpoint.category,
            passed=passed,
            response=response,
            detail="" if passed else f"missing {checkpoint.expect_contains!r}",
        )

    if checkpoint.category is CheckpointCategory.ACCESS:
        leaked = any(target in response for target in checkpoint.leak_targets)
        has_memory = bool(response.strip())
        violation = leaked or (
            checkpoint.require_no_memory and has_memory
        )
        detail = ""
        if leaked:
            detail = "leak target present in response"
        elif checkpoint.require_no_memory and has_memory:
            detail = "unauthorized memory returned"
        return CheckpointResult(
            episode_id=episode_id,
            checkpoint_id=checkpoint.checkpoint_id,
            category=checkpoint.category,
            passed=not violation,
            response=response,
            detail=detail,
        )

    if checkpoint.category is CheckpointCategory.FORGETTING:
        recalled = (
            checkpoint.expect_contains is not None
            and checkpoint.expect_contains in response
        )
        has_memory = bool(response.strip())
        embedding_alive = False
        if checkpoint.expect_contains is not None:
            embedding_alive = (
                stub.embedding_vector_id(checkpoint.expect_contains) is not None
            )
        failure = recalled or (
            checkpoint.require_no_memory and has_memory
        ) or embedding_alive
        detail = ""
        if recalled:
            detail = "deleted lesson still in response"
        elif checkpoint.require_no_memory and has_memory:
            detail = "memory returned after deletion"
        elif embedding_alive:
            detail = "embedding index still maps deleted row"
        return CheckpointResult(
            episode_id=episode_id,
            checkpoint_id=checkpoint.checkpoint_id,
            category=checkpoint.category,
            passed=not failure,
            response=response,
            detail=detail,
        )

    return CheckpointResult(
        episode_id=episode_id,
        checkpoint_id=checkpoint.checkpoint_id,
        category=checkpoint.category,
        passed=False,
        response=response,
        detail=f"unknown category: {checkpoint.category}",
    )


def run_episode(stub: GateMemAgentStub, episode: Episode) -> tuple[CheckpointResult, ...]:
    """Replay one fixture episode and return per-checkpoint outcomes."""
    stub.reset()
    for write in episode.writes:
        stub.ingest(write)
    for bind in episode.embedding_binds:
        stub.bind_embedding(bind.lesson_contains, bind.vector_id)
    for forget in episode.forgets:
        stub.forget(forget)
    return tuple(
        evaluate_checkpoint(stub, episode.episode_id, checkpoint)
        for checkpoint in episode.checkpoints
    )


def aggregate_mgs(results: tuple[CheckpointResult, ...]) -> MGSScore:
    """Compute GateMem U, A, F, and MGS = U * (1 - A) * (1 - F)."""
    utility_total = sum(
        1 for r in results if r.category is CheckpointCategory.UTILITY
    )
    access_total = sum(
        1 for r in results if r.category is CheckpointCategory.ACCESS
    )
    forgetting_total = sum(
        1 for r in results if r.category is CheckpointCategory.FORGETTING
    )

    utility_passes = sum(
        1
        for r in results
        if r.category is CheckpointCategory.UTILITY and r.passed
    )
    access_violations = sum(
        1
        for r in results
        if r.category is CheckpointCategory.ACCESS and not r.passed
    )
    forgetting_failures = sum(
        1
        for r in results
        if r.category is CheckpointCategory.FORGETTING and not r.passed
    )

    utility = utility_passes / utility_total if utility_total else 1.0
    access_violation = access_violations / access_total if access_total else 0.0
    forgetting_failure = (
        forgetting_failures / forgetting_total if forgetting_total else 0.0
    )
    mgs = utility * (1.0 - access_violation) * (1.0 - forgetting_failure)

    return MGSScore(
        utility=utility,
        access_violation=access_violation,
        forgetting_failure=forgetting_failure,
        mgs=mgs,
        utility_total=utility_total,
        access_total=access_total,
        forgetting_total=forgetting_total,
        utility_passes=utility_passes,
        access_violations=access_violations,
        forgetting_failures=forgetting_failures,
    )


def run_harness(
    episodes: tuple[Episode, ...] | None = None,
    *,
    stub: GateMemAgentStub | None = None,
) -> HarnessReport:
    """Run fixture episodes and emit an MGS report for CI gating."""
    episode_list = SUBSET_EPISODES if episodes is None else episodes
    agent = stub or GateMemAgentStub()
    all_results: list[CheckpointResult] = []
    for episode in episode_list:
        all_results.extend(run_episode(agent, episode))
    results_tuple = tuple(all_results)
    return HarnessReport(
        score=aggregate_mgs(results_tuple),
        checkpoints=results_tuple,
    )
