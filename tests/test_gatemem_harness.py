"""GateMem regression harness — subset episodes and MGS for CI gating (r5)."""

from __future__ import annotations

from verified_memory_gate import (
    GateMemAgentStub,
    GateMemThresholds,
    SUBSET_EPISODES,
    aggregate_mgs,
    run_episode,
    run_harness,
)
from verified_memory_gate.gatemem_episodes import CheckpointCategory


def test_subset_episodes_cover_all_probe_families() -> None:
    categories = {cp.category for ep in SUBSET_EPISODES for cp in ep.checkpoints}
    assert CheckpointCategory.UTILITY in categories
    assert CheckpointCategory.ACCESS in categories
    assert CheckpointCategory.FORGETTING in categories


def test_harness_perfect_mgs_on_memory_gate_stub() -> None:
    report = run_harness()
    score = report.score

    assert score.utility == 1.0
    assert score.access_violation == 0.0
    assert score.forgetting_failure == 0.0
    assert score.mgs == 1.0
    assert all(cp.passed for cp in report.checkpoints)


def test_harness_passes_default_ci_thresholds() -> None:
    report = run_harness()
    assert report.passes(GateMemThresholds())


def test_forgetting_probe_catches_embedding_ghost() -> None:
    stub = GateMemAgentStub()
    episode = next(ep for ep in SUBSET_EPISODES if ep.episode_id == "household-forget-grocery")
    results = run_episode(stub, episode)
    forgetting = next(r for r in results if r.category is CheckpointCategory.FORGETTING)
    assert forgetting.passed


def test_aggregate_mgs_formula() -> None:
    from verified_memory_gate.gatemem_harness import CheckpointResult

    results = (
        CheckpointResult("e1", "u1", CheckpointCategory.UTILITY, True, "ok"),
        CheckpointResult("e1", "a1", CheckpointCategory.ACCESS, False, "leaked"),
        CheckpointResult("e1", "f1", CheckpointCategory.FORGETTING, True, ""),
    )
    score = aggregate_mgs(results)
    assert score.utility == 1.0
    assert score.access_violation == 1.0
    assert score.forgetting_failure == 0.0
    assert score.mgs == 0.0
