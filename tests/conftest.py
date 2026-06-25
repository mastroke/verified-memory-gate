"""Shared fixtures for EDV commit tests."""

from __future__ import annotations

import pytest

from verified_memory_gate import (
    DistillContext,
    EDVPipeline,
    ExecuteStage,
    ExecutorTrace,
    InMemoryStore,
    MemoryGate,
    MemoryScope,
)


def dual_traces(
    lesson: str,
    *,
    trace_id: str | None = None,
    evidence: tuple[str, ...] = (),
    metadata: dict | None = None,
) -> tuple[ExecutorTrace, ExecutorTrace]:
    """Build two heterogeneous executor traces for EDV commit."""
    shared: dict = dict(metadata or {})
    return (
        ExecutorTrace(
            executor_id="research-agent",
            content=lesson,
            trace_id=trace_id,
            evidence=evidence,
            metadata=shared,
        ),
        ExecutorTrace(
            executor_id="audit-agent",
            content=f"cross-check: {lesson}",
            trace_id=trace_id,
            metadata=shared,
        ),
    )


def distill_context(
    *,
    principal: str = "research-agent",
    scope: MemoryScope | str = MemoryScope.TEAM,
    relationship: str = "derived_from",
    classification: str = "episodic",
    trace_id: str | None = None,
    metadata: dict | None = None,
) -> DistillContext:
    return DistillContext(
        principal=principal,
        scope=scope,
        relationship=relationship,
        classification=classification,
        trace_id=trace_id,
        metadata=dict(metadata or {}),
    )


@pytest.fixture
def gate() -> MemoryGate:
    return MemoryGate(
        store=InMemoryStore(),
        pipeline=EDVPipeline(execute=ExecuteStage(min_traces=1)),
    )
